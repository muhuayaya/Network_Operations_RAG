"""使用默认未配置业务处理器的安全 MCP stdio 适配器。"""

from netops_copilot.interfaces.mcp import create_mcp_server

if __name__ == "__main__":
    create_mcp_server().run_stdio()
