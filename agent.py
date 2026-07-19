import asyncio
import ollama
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from rag_module import retrieve_best_tool  # Importujeme náš RAG

MODEL_NAME = "qwen2.5-coder:3b"

async def run_agent():
    server_params = StdioServerParameters(
        command="python",
        args=["grass_server.py"]
    )

    print("1. Starting and connecting to local GRASS MCP Server...")
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # 1. Uživatel zadá dotaz v angličtině
            user_prompt = "Hey, please generate a 250 meters buffer zone around the main_roads layer."
            print(f"\n👤 User: \"{user_prompt}\"")

            # 2. RAG fáze - Vyhledáme nejlepší nástroj z naší znalostní báze
            target_tool_name = retrieve_best_tool(user_prompt)

            # 3. Načteme nástroje z MCP serveru a profiltrujeme je
            tools_response = await session.list_tools()
            ollama_tools = []

            for tool in tools_response.tools:
                # LLM zpřístupníme POUZE ten nástroj, který vybral RAG!
                if tool.name == target_tool_name:
                    ollama_tools.append({
                        'type': 'function',
                        'function': {
                            'name': tool.name,
                            'description': tool.description,
                            'parameters': tool.inputSchema
                        }
                    })

            print(f"📦 Active tools exposed to LLM: {[t['function']['name'] for t in ollama_tools]}")

            # 4. Volání lokálního LLM
            print(f"🤖 Sending request to {MODEL_NAME}...")

            messages = [
                {
                    'role': 'system',
                    'content': 'You are a professional GIS assistant. You must communicate strictly in English.'
                },
                {
                    'role': 'user',
                    'content': user_prompt
                }
            ]

            response = ollama.chat(
                model=MODEL_NAME,
                messages=messages,
                tools=ollama_tools
            )

            # 5. Zpracování volání nástroje s naším fallbackem
            tool_calls = response.message.tool_calls
            if not tool_calls and response.message.content:
                # Fallback pro textový JSON z malých modelů
                import json
                text_content = response.message.content.strip()
                if text_content.startswith("```"):
                    text_content = "\n".join(text_content.split("\n")[1:-1]).strip()
                try:
                    parsed_json = json.loads(text_content)
                    if isinstance(parsed_json, dict) and "name" in parsed_json:
                        class MockFunction:
                            def __init__(self, name, arguments):
                                self.name = name
                                self.arguments = arguments
                        class MockToolCall:
                            def __init__(self, function):
                                self.function = function
                        tool_calls = [MockToolCall(MockFunction(parsed_json["name"], parsed_json.get("arguments", {})))]
                        print("⚠️ Fallback Parser activated: Extracted JSON from text.")
                except json.JSONDecodeError:
                    pass

            # Spuštění nástroje
            if tool_calls:
                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = tool_call.function.arguments

                    print(f"\n🎯 AI decided to call: {tool_name}")
                    print(f"   With arguments: {tool_args}")

                    print(f"⚙️ Running command on GRASS MCP server...")
                    result = await session.call_tool(tool_name, arguments=tool_args)
                    output_text = result.content[0].text
                    print(f"📥 GRASS Response: {output_text}")

                    # Finální odpověď v angličtině
                    messages.append(response.message)
                    messages.append({
                        'role': 'tool',
                        'content': output_text,
                        'name': tool_name
                    })

                    print("✍️ Generating final response...")
                    final_response = ollama.chat(model=MODEL_NAME, messages=messages)
                    print(f"\n🤖 Agent final answer:\n{final_response.message.content}")
            else:
                print(f"\n🤖 Agent responded without tools:\n{response.message.content}")

if __name__ == "__main__":
    asyncio.run(run_agent())
