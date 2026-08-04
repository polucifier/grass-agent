import asyncio
import json
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import AgentConfig
from grass_context import GRASSContext
from llm_provider import LLMProvider, OllamaProvider, GeminiProvider, create_provider, _format_tool, _format_server_tool
from tool_selector import ToolSelector, ToolDef

GRASS_MCP_SERVER = "grass_mcp_server.py"

BASE_SYSTEM_PROMPT = (
    "You are a professional GIS assistant specializing in GRASS GIS. "
    "You must communicate strictly in English. "
    "IMPORTANT: When a tool is available that matches the user's request, you MUST call it. "
    "Do not just describe the command — execute the tool and report the actual result. "
    "If a tool fails, explain what went wrong and suggest an alternative. "
    "If the user asks a question that does not require a tool, respond conversationally."
)


def build_system_prompt(grass_ctx: GRASSContext) -> str:
    return BASE_SYSTEM_PROMPT + grass_ctx.to_system_prompt_suffix()


def _make_ollama_tool_call_msg(tool_call, call_id):
    return {
        "role": "assistant",
        "tool_calls": [{"function": {"name": tool_call.name, "arguments": tool_call.arguments}}],
    }


def _make_api_tool_call_msg(tool_call, call_id):
    return {
        "role": "assistant",
        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": tool_call.name, "arguments": json.dumps(tool_call.arguments)}}],
    }


def _make_tool_result_msg(tool_call, output_text, call_id):
    return {"role": "tool", "content": output_text, "tool_call_id": call_id}


def _is_ollama(provider: LLMProvider) -> bool:
    return isinstance(provider, OllamaProvider)


async def run_agent(config: AgentConfig):
    provider = create_provider(config)
    grass_ctx = GRASSContext()
    selector = ToolSelector(provider, threshold=config.similarity_threshold)

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[GRASS_MCP_SERVER],
    )

    print(f"Provider: {type(provider).__name__} | Model: ", end="")
    print(provider.model if hasattr(provider, "model") else "unknown")
    print(f"Location: {grass_ctx.location} | CRS: {grass_ctx.crs}")
    print(f"Tool registry: {len(selector.registry)} tools")

    print("Starting MCP server...")
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Build MCP tool schemas from server
            server_tools = {t.name: t for t in (await session.list_tools()).tools}

            conversation_history: list[dict] = [
                {"role": "system", "content": build_system_prompt(grass_ctx)},
            ]

            print("Agent ready. Commands: 'quit', 'clear' (reset history), or type a request.\n")

            while True:
                try:
                    user_prompt = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\nExiting.")
                    break

                if not user_prompt:
                    continue
                if user_prompt.lower() in ("quit", "exit", "q"):
                    print("Exiting.")
                    break
                if user_prompt.lower() == "clear":
                    conversation_history = [{"role": "system", "content": build_system_prompt(grass_ctx)}]
                    print("Conversation history cleared.\n")
                    continue

                try:
                    await process_message(
                        session, provider, config, selector,
                        server_tools, conversation_history, user_prompt,
                    )
                except Exception as e:
                    print(f"Error: {e}\n")


async def process_message(
    session,
    provider: LLMProvider,
    config: AgentConfig,
    selector: ToolSelector,
    server_tools: dict,
    messages: list[dict],
    user_prompt: str,
):
    messages.append({"role": "user", "content": user_prompt})

    # Stage 1+2: Select relevant tools
    selected_defs = selector.select_tools(user_prompt)

    # Filter to tools that exist on the MCP server
    mcp_tools = []
    for tool_def in selected_defs:
        if tool_def.name in server_tools:
            mcp_tools.append(_format_tool(tool_def))

    # Fallback: if no selector tools matched, pass top server tools
    # so the LLM can still decide whether to use one or respond conversationally
    if not mcp_tools:
        mcp_tools = [_format_server_tool(name, server_tools[name]) for name in list(server_tools)[:10]]

    print(f"Tools available to LLM: {[t['function']['name'] for t in mcp_tools]}")

    try:
        response = provider.chat(list(messages), tools=mcp_tools)
    except Exception as e:
        print(f"LLM error: {e}\n")
        return

    # Conversational response — no tool call
    if not response.tool_calls:
        assistant_content = response.content or ""
        messages.append({"role": "assistant", "content": assistant_content})
        print(f"\n{assistant_content}\n")
        return

    # Tool call chain
    for chain_step in range(config.max_tool_calls_per_turn):
        if not response.tool_calls:
            break

        for i, tool_call in enumerate(response.tool_calls):
            print(f"Calling: {tool_call.name}({tool_call.arguments})")

            try:
                result = await session.call_tool(tool_call.name, arguments=tool_call.arguments)

                if result.isError:
                    output_text = f"Error: {result.content}"
                elif result.content:
                    output_text = result.content[0].text
                else:
                    output_text = "Tool returned no output."

                print(f"Result: {output_text}")
            except Exception as e:
                output_text = f"Error executing tool '{tool_call.name}': {e}"
                print(output_text)

            call_id = f"call_{chain_step}_{i}"

            if _is_ollama(provider):
                messages.append(_make_ollama_tool_call_msg(tool_call, call_id))
            else:
                messages.append(_make_api_tool_call_msg(tool_call, call_id))

            messages.append(_make_tool_result_msg(tool_call, output_text, call_id))

        try:
            response = provider.chat(list(messages), tools=mcp_tools)
        except Exception as e:
            print(f"LLM error: {e}\n")
            return

    assistant_content = response.content or ""
    messages.append({"role": "assistant", "content": assistant_content})
    print(f"\n{assistant_content}\n")


if __name__ == "__main__":
    config = AgentConfig.from_env()
    asyncio.run(run_agent(config))
