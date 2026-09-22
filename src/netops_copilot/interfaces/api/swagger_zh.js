// Translate Swagger UI's presentation text without changing API identifiers.
(() => {
  "use strict";

  const translations = new Map(Object.entries({
    "Try it out": "试一试",
    "Show/Hide": "显示/隐藏",
    "List Operations": "接口列表",
    "Expand Operations": "展开接口",
    "Cancel": "取消",
    "Reset": "重置",
    "Execute": "执行",
    "Clear": "清空",
    "Parameters": "参数",
    "No parameters": "无参数",
    "Request body": "请求体",
    "required": "必填",
    "optional": "可选",
    "Example Value": "示例值",
    "Example": "示例",
    "Examples": "示例",
    "Schema": "结构",
    "Schemas": "数据结构",
    "Edit Value": "编辑内容",
    "Responses": "响应",
    "Response body": "响应内容",
    "Response headers": "响应头",
    "Request URL": "请求地址",
    "Server response": "服务器响应",
    "Code": "状态码",
    "Details": "详情",
    "Description": "说明",
    "Links": "链接",
    "Media type": "媒体类型",
    "Controls Accept header.": "设置 Accept 请求头。",
    "Curl": "cURL 命令",
    "Download": "下载",
    "Copy": "复制",
    "Copy to clipboard": "复制到剪贴板",
    "Copied": "已复制",
    "Raw": "原始内容",
    "Read more": "查看更多",
    "OpenAPI definition": "OpenAPI 定义",
    "Models": "模型",
    "Model Schema": "模型结构",
    "Name": "名称",
    "Value": "值",
    "Type": "类型",
    "Format": "格式",
    "Pattern": "格式模式",
    "Maximum": "最大值",
    "Minimum": "最小值",
    "Max length": "最大长度",
    "Min length": "最小长度",
    "Response class": "响应类型",
    "Response content type": "响应内容类型",
    "Select a server": "选择服务器",
    "Server Variables": "服务器变量",
    "Extensions": "扩展",
    "Apply": "应用",
    "Scopes": "作用域",
    "No links": "无链接",
    "Expand all": "全部展开",
    "Collapse all": "全部收起",
    "Authorize": "授权",
    "Available authorizations": "可用的授权方式",
    "Logout": "退出授权",
    "Close": "关闭",
    "Servers": "服务器",
    "Default": "默认",
    "default": "默认接口",
    "Select a definition": "选择接口定义",
    "Loading...": "加载中...",
    "Failed to load API definition.": "加载接口定义失败。",
    "Fetch error": "请求错误",
    "Undocumented": "未记录",
    "Successful Response": "成功响应",
    "Validation Error": "参数校验错误",
    "No content": "无内容",
    "No response": "无响应",
    "No operations defined in spec!": "接口定义中没有操作！",
    "Could not render this component, see the console.": "无法显示此组件，请查看控制台。",
  }));

  const excluded = "pre, code, textarea, .opblock-summary-path, .opblock-summary-method, .prop-name";
  const attributes = ["title", "aria-label", "placeholder", "alt"];

  function translate(value) {
    const trimmed = value.trim();
    const replacement = translations.get(trimmed);
    if (!replacement) return value;
    return value.replace(trimmed, replacement);
  }

  function translateTree(root) {
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (node.parentElement?.closest(excluded)) continue;
      const translated = translate(node.nodeValue);
      if (translated !== node.nodeValue) node.nodeValue = translated;
    }
    for (const element of root.querySelectorAll("*")) {
      if (element.closest(excluded)) continue;
      for (const attribute of attributes) {
        const value = element.getAttribute(attribute);
        if (value === null) continue;
        const translated = translate(value);
        if (translated !== value) element.setAttribute(attribute, translated);
      }
    }
  }

  document.documentElement.lang = "zh-CN";
  const style = document.createElement("style");
  style.textContent = '.swagger-ui .parameter__name.required:after { content: "必填" !important; }';
  document.head.appendChild(style);
  const root = document.getElementById("swagger-ui");
  if (!root) return;
  let pending = false;
  const observer = new MutationObserver(() => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      translateTree(root);
    });
  });
  observer.observe(root, { childList: true, subtree: true, characterData: true, attributes: true });
  translateTree(root);
})();
