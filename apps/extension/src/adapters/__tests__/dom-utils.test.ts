// @vitest-environment jsdom
/**
 * DOM 工具层测试：候选选择器兜底与角色推断。
 *
 * 平台常有多套 DOM 变体（灰度 / A-B / 新旧版并存），因此选择器支持候选列表；
 * 角色推断必须「拿不准就返回 unknown」，绝不猜测。
 */

import { beforeEach, describe, expect, it } from "vitest";
import {
  describeSelector,
  extractBlocks,
  inferRole,
  queryAll,
  queryDeepest,
  queryFirst,
  readTitle,
} from "../dom-utils";

function mount(html: string): void {
  document.body.innerHTML = html;
}

describe("候选选择器", () => {
  beforeEach(() => mount(""));

  it("返回第一个有命中的候选", () => {
    mount('<div class="b">1</div><div class="b">2</div>');
    expect(queryAll(document, [".a", ".b", ".c"])).toHaveLength(2);
  });

  it("优先级靠前的候选胜出", () => {
    mount('<div class="a">1</div><div class="b">2</div><div class="b">3</div>');
    expect(queryAll(document, [".a", ".b"])).toHaveLength(1);
  });

  it("全部落空返回空数组（而不是退化成宽泛匹配）", () => {
    mount('<div class="x">1</div>');
    expect(queryAll(document, [".a", ".b"])).toEqual([]);
  });

  it("queryFirst 同样按候选顺序取第一个", () => {
    mount('<div class="b" id="first">1</div>');
    expect(queryFirst(document, [".a", ".b"])?.id).toBe("first");
    expect(queryFirst(document, [".a"])).toBeNull();
  });

  it("describeSelector 便于错误信息展示", () => {
    expect(describeSelector(".a")).toBe(".a");
    expect(describeSelector([".a", ".b"])).toBe(".a | .b");
  });
});

describe("inferRole", () => {
  beforeEach(() => mount(""));

  it("识别标准角色", () => {
    mount('<div id="u" data-role="user"></div><div id="a" data-role="assistant"></div>');
    expect(inferRole(document.getElementById("u")!, "data-role")).toBe("user");
    expect(inferRole(document.getElementById("a")!, "data-role")).toBe("assistant");
  });

  it("识别平台变体写法（human / ai / bot）", () => {
    mount('<div id="h" data-role="human"></div><div id="i" data-role="ai"></div>');
    expect(inferRole(document.getElementById("h")!, "data-role")).toBe("user");
    expect(inferRole(document.getElementById("i")!, "data-role")).toBe("assistant");
  });

  it("多属性候选：按顺序取第一个有效的", () => {
    mount('<div id="m" data-author-role="user"></div>');
    expect(inferRole(document.getElementById("m")!, ["data-role", "data-author-role"])).toBe("user");
  });

  it("角色属性在祖先节点上时向上查找", () => {
    mount('<div data-role="assistant"><span id="inner"></span></div>');
    expect(inferRole(document.getElementById("inner")!, "data-role")).toBe("assistant");
  });

  it("class 命名作为次级策略", () => {
    mount('<div id="q" class="question-bubble"></div><div id="r" class="reply-bubble"></div>');
    expect(inferRole(document.getElementById("q")!, "data-role")).toBe("user");
    expect(inferRole(document.getElementById("r")!, "data-role")).toBe("assistant");
  });

  it("拿不准时返回 unknown（不猜测）", () => {
    mount('<div id="x" class="card"></div>');
    expect(inferRole(document.getElementById("x")!, "data-role")).toBe("unknown");
  });
});

describe("角色标记（无 role 属性的平台，如豆包）", () => {
  beforeEach(() => mount(""));

  it("AI 消息：祖先带 data-reply-message=true 判为 assistant", () => {
    mount('<div data-reply-message="true"><div id="m"></div></div>');
    expect(inferRole(document.getElementById("m")!, "data-role", { assistant: '[data-reply-message="true"]' })).toBe(
      "assistant",
    );
  });

  it("用户消息：自身带 justify-end 判为 user", () => {
    mount('<div id="m" class="flex-row flex w-full justify-end"></div>');
    expect(inferRole(document.getElementById("m")!, "data-role", { user: ".justify-end" })).toBe("user");
  });

  it("两种标记同时命中时 assistant 优先", () => {
    mount('<div data-reply-message="true"><div id="m" class="justify-end"></div></div>');
    expect(
      inferRole(document.getElementById("m")!, "data-role", {
        assistant: '[data-reply-message="true"]',
        user: ".justify-end",
      }),
    ).toBe("assistant");
  });

  it("标记只在 3 层祖先内生效（避免把整页容器误判）", () => {
    mount('<div data-reply-message="true"><i><i><i><i><div id="deep"></div></i></i></i></i></div>');
    expect(
      inferRole(document.getElementById("deep")!, "data-role", { assistant: '[data-reply-message="true"]' }),
    ).toBe("unknown");
  });

  it("没有标记时退回属性与 class 判定", () => {
    mount('<div id="a" data-role="user"></div>');
    expect(inferRole(document.getElementById("a")!, "data-role", {})).toBe("user");
  });
});

describe("queryDeepest（嵌套重复渲染的标题）", () => {
  beforeEach(() => mount(""));

  it("取最内层节点，避免拿到重复文本", () => {
    // 豆包式三层嵌套：最外层 textContent 是「标题标题标题」
    mount(
      '<div id="root"><span class="whitespace-nowrap">标题<span class="whitespace-nowrap">标题' +
        '<span class="whitespace-nowrap">标题</span></span></span></div>',
    );
    const root = document.getElementById("root")!;
    expect(queryAll(root, '[class*="whitespace-nowrap"]')).toHaveLength(3);
    expect(queryFirst(root, '[class*="whitespace-nowrap"]')?.textContent).toBe("标题标题标题");
    expect(queryDeepest(root, '[class*="whitespace-nowrap"]')?.textContent).toBe("标题");
  });

  it("无命中时返回 null", () => {
    expect(queryDeepest(document, ".nope")).toBeNull();
  });

  it("readTitle 优先取元素自身文本，避开内层重复渲染", () => {
    // 线上实测结构：外层带 whitespace-nowrap，内层不带但重复同一段文字
    mount(
      '<div id="root"><span class="whitespace-nowrap flex-1">IP地址' +
        '<span class="absolute inset-0">IP地址</span></span></div>',
    );
    const root = document.getElementById("root")!;
    const el = queryDeepest(root, '[class*="whitespace-nowrap"]')!;
    expect(el.textContent).toBe("IP地址IP地址");
    expect(readTitle(el)).toBe("IP地址");
  });

  it("readTitle 对纯容器元素回退到整树文本", () => {
    mount('<div id="wrap"><span>真实标题</span></div>');
    expect(readTitle(document.getElementById("wrap")!)).toBe("真实标题");
  });

  it("候选列表同样适用", () => {
    mount('<div class="a">X</div><div class="a">X2</div>');
    expect(queryDeepest(document, [".missing", ".a"])?.textContent).toBe("X2");
  });
});

describe("extractBlocks", () => {
  beforeEach(() => mount(""));

  it("保留代码块语言与内容", () => {
    mount('<div id="c"><p>看这里</p><pre><code class="language-sql">SELECT 1;</code></pre></div>');
    const blocks = extractBlocks(document.getElementById("c")!);
    const code = blocks.find((b) => b.type === "code");
    expect(code).toMatchObject({ type: "code", language: "sql" });
    expect(code?.type === "code" && code.text).toContain("SELECT 1;");
  });

  it("表格转 Markdown 保留表头分隔行", () => {
    mount('<div id="t"><table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table></div>');
    const blocks = extractBlocks(document.getElementById("t")!);
    const text = blocks.map((b) => (b.type === "text" ? b.text : "")).join("\n");
    expect(text).toContain("| A | B |");
    expect(text).toContain("| --- | --- |");
  });

  it("空容器返回空的文本块而不是抛错", () => {
    mount('<div id="e"></div>');
    expect(extractBlocks(document.getElementById("e")!)).toEqual([{ type: "text", text: "" }]);
  });
});
