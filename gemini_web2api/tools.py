"""Tool calling and multimodal message parsing."""
import json
import re
import uuid
import base64
import binascii
import io
from urllib.parse import unquote_to_bytes

MAX_IMAGE_B64_SIZE = 50000  # ~37KB raw image


def _compress_b64_if_needed(b64: str) -> str:
    """Compress image if base64 is too large for text embedding."""
    if len(b64) <= MAX_IMAGE_B64_SIZE:
        return b64
    try:
        from PIL import Image
        img_data = base64.b64decode(b64)
        img = Image.open(io.BytesIO(img_data))
        # Resize to max 256px on longest side
        max_dim = 256
        ratio = min(max_dim / img.width, max_dim / img.height)
        if ratio < 1:
            img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
        # Convert to JPEG with quality reduction
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=60)
        compressed = base64.b64encode(buf.getvalue()).decode()
        return compressed
    except Exception:
        # If PIL not available, truncate (model will get partial data)
        return b64[:MAX_IMAGE_B64_SIZE]


def _build_tool_choice_instruction(tool_choice, tool_defs: list) -> str:
    """Build tool_choice constraint instruction.

    tool_choice values:
      - "none": do not call any tool
      - "auto": decide whether to call tools (default)
      - "required": must call at least one tool
      - {"type": "function", "function": {"name": "xxx"}}: must call specific tool
    """
    if tool_choice == "none":
        return "\n\nIMPORTANT: Do NOT call any tools. Respond with text only."
    if tool_choice == "required":
        return "\n\nIMPORTANT: You MUST call at least one tool. Do not respond with text only."
    if isinstance(tool_choice, dict):
        fn_name = tool_choice.get("function", {}).get("name", "")
        if fn_name:
            return f'\n\nIMPORTANT: You MUST call the tool "{fn_name}". Do not call other tools.'
    return ""


def _decode_data_url(url: str):
    match = re.match(r"^data:([^;,]+)?(;base64)?,(.*)$", url, re.DOTALL)
    if not match:
        return None
    mime = match.group(1) or "image/png"
    is_base64 = bool(match.group(2))
    data = match.group(3)
    try:
        if is_base64:
            return base64.b64decode(data, validate=True), mime
        return unquote_to_bytes(data), mime
    except (ValueError, TypeError, binascii.Error):
        return None


def _image_from_url(url: str, mime: str = None):
    if not isinstance(url, str) or not url:
        return None
    if url.startswith("data:"):
        return _decode_data_url(url)
    return url, mime or "image/png"


def _image_from_part(part: dict):
    part_type = part.get("type")
    if part_type == "image_url":
        image_url = part.get("image_url", {})
        if isinstance(image_url, dict):
            return _image_from_url(image_url.get("url"), image_url.get("mime_type"))
        return _image_from_url(image_url)
    if part_type in ("input_image", "image"):
        image_url = part.get("image_url") or part.get("url")
        if isinstance(image_url, dict):
            return _image_from_url(image_url.get("url"), image_url.get("mime_type"))
        if image_url:
            return _image_from_url(image_url, part.get("mime_type"))
        image_data = part.get("data") or part.get("base64")
        if isinstance(image_data, str):
            mime = part.get("mime_type") or part.get("media_type") or "image/png"
            if image_data.startswith("data:"):
                return _decode_data_url(image_data)
            try:
                return base64.b64decode(image_data, validate=True), mime
            except (ValueError, TypeError, binascii.Error):
                return None
    return None


def messages_to_prompt(messages: list, tools: list = None, tool_choice=None) -> tuple:
    """Convert OpenAI messages to (prompt_str, images_list).

    Returns (prompt, images) where images is a list of (bytes, mime_type) tuples.
    """
    parts = []
    images = []

    if tools and tool_choice != "none":
        tool_defs = []
        for tool in tools:
            fn = tool.get("function", tool) if tool.get("type") == "function" else tool
            tool_defs.append({
                "name": fn.get("name", tool.get("name", "")),
                "description": fn.get("description", tool.get("description", "")),
                "parameters": fn.get("parameters", tool.get("parameters", {})),
            })
        if tool_defs:
            constraint = _build_tool_choice_instruction(tool_choice, tool_defs)
            parts.append(
                "# Tool Use\n\n"
                "You can call the following tools. Call format:\n"
                '```tool_call\n{"name": "func_name", "arguments": {...}}\n```\n'
                "When calling tools, output ONLY the tool_call block(s).\n"
                "CRITICAL RULES FOR TOOLS:\n"
                "1. ONLY call tools that are listed in Available tools below. NEVER invent or hallucinate new tool names (e.g. do not invent format_final_json_response).\n"
                "2. When you have completed all tool calls and are ready to present the final answer to the user, output your answer directly as text (or JSON if requested), NEVER wrap the final answer inside a tool_call block.\n\n"
                f"Available tools:\n{json.dumps(tool_defs, indent=2)}"
                f"{constraint}"
            )

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, list):
            text_parts = []
            for c in content:
                if c.get("type") in ("text", "input_text"):
                    text_parts.append(c.get("text", ""))
                else:
                    image = _image_from_part(c)
                    if image:
                        images.append(image)
                        text_parts.append("[Image attached]")
            content = " ".join(text_parts)

        if role == "system":
            parts.append(f"[System instruction]: {content}")
        elif role == "assistant":
            if msg.get("tool_calls"):
                tc_strs = []
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    tc_strs.append(
                        f'```tool_call\n{{"name": "{fn.get("name")}", '
                        f'"arguments": {fn.get("arguments", "{}")}}}\n```'
                    )
                parts.append(f"[Assistant]: {content or ''}\n" + "\n".join(tc_strs))
            else:
                parts.append(f"[Assistant]: {content}")
        elif role == "tool":
            parts.append(f"[Tool result for {msg.get('name', '')}]: {content}")
        else:
            parts.append(content if content else "")

    prompt = "\n\n".join(p for p in parts if p)
    return prompt, images


def _repair_json(raw: str):
    """Safely parse JSON from model output, fixing unescaped newlines and common formatting issues."""
    raw = raw.strip()
    # 1. Try standard parsing with strict=False (handles unescaped control characters)
    try:
        return json.loads(raw, strict=False)
    except Exception:
        pass

    # 2. Try removing trailing commas
    cleaned = re.sub(r',\s*([\}\]])', r'\1', raw)
    try:
        return json.loads(cleaned, strict=False)
    except Exception:
        pass

    # 3. Escape literal newlines/tabs inside quotes
    def escape_newlines_in_strings(s):
        result = []
        in_string = False
        escaped = False
        for c in s:
            if c == '"' and not escaped:
                in_string = not in_string
                result.append(c)
            elif c == '\\' and not escaped:
                escaped = True
                result.append(c)
            elif c == '\n' and in_string:
                result.append('\\n')
            elif c == '\r' and in_string:
                result.append('\\r')
            elif c == '\t' and in_string:
                result.append('\\t')
            else:
                result.append(c)
            if c != '\\':
                escaped = False
        return "".join(result)

    try:
        return json.loads(escape_newlines_in_strings(raw), strict=False)
    except Exception:
        pass

    # 4. Fallback regex extraction for {"name": "...", "arguments": ...} or {"name": "...", "args": ...}
    name_m = re.search(r'"name"\s*:\s*"([^"]+)"', raw)
    if name_m:
        name = name_m.group(1)
        args_m = re.search(r'"(?:arguments|args)"\s*:\s*(\{.*\}|\[.*\]|"[^"]*")', raw, re.DOTALL)
        if args_m:
            try:
                args = json.loads(args_m.group(1), strict=False)
                return {"name": name, "arguments": args}
            except Exception:
                return {"name": name, "arguments": {"input": args_m.group(1)}}
        return {"name": name, "arguments": {}}

    return None


def parse_tool_calls(text: str, valid_tool_names: list = None) -> tuple:
    """Extract tool_call blocks. Returns (clean_text, tool_calls_list).

    If valid_tool_names is provided, only tools matching valid_tool_names are returned
    as tool_calls. If the model emitted a pseudo-tool (e.g. format_final_json_response),
    its arguments are unpacked directly into clean_text as valid JSON content so downstream
    output parsers receive it cleanly.
    """
    if not text:
        return "", []

    tool_calls = []
    pattern = r'```tool_call\s*\n(.*?)(?:\n```|$)'
    clean_parts = []
    last_end = 0

    valid_set = set(valid_tool_names) if valid_tool_names else None

    for m in re.finditer(pattern, text, re.DOTALL):
        clean_parts.append(text[last_end:m.start()])
        last_end = m.end()
        raw_block = m.group(1).strip()
        data = _repair_json(raw_block)

        if not data or not isinstance(data, dict) or "name" not in data:
            # If parsing completely failed, keep raw text so content is never lost
            clean_parts.append(m.group(0))
            continue

        fn_name = data["name"]
        args = data.get("arguments", data.get("args", {}))

        # Check if fn_name is a pseudo-tool or not in valid tools
        if valid_set is not None and fn_name not in valid_set:
            # Check for pseudo-tool names like format_final_json_response, final_answer, etc.
            if any(term in fn_name.lower() for term in ("format", "final", "json", "response", "answer", "output")):
                if isinstance(args, dict) and "output" in args:
                    clean_parts.append(json.dumps(args["output"], indent=2, ensure_ascii=False))
                elif isinstance(args, (dict, list)):
                    clean_parts.append(json.dumps(args, indent=2, ensure_ascii=False))
                else:
                    clean_parts.append(str(args))
            else:
                # Unknown tool: keep as text rather than sending an invalid tool call that will crash downstream
                clean_parts.append(m.group(0))
            continue

        # Valid tool call
        if not isinstance(args, str):
            args_str = json.dumps(args, ensure_ascii=False)
        else:
            args_str = args

        tool_calls.append({
            "id": f"call_{uuid.uuid4().hex[:8]}",
            "type": "function",
            "function": {
                "name": fn_name,
                "arguments": args_str,
            },
        })

    clean_parts.append(text[last_end:])
    clean = "".join(clean_parts).strip()
    if not tool_calls and not clean and text.strip():
        clean = text.strip()

    return clean, tool_calls


# ─── Google Native API helpers ─────────────────────────────────────────────────


def build_tool_prompt(tool_defs: list) -> str:
    """Build natural tool-use prompt for Gemini Web that avoids prompt-injection detection."""
    tool_spec = json.dumps(tool_defs, indent=2, ensure_ascii=False)
    return (
        "# Tool Use\n\n"
        "You can call the following tools to help accomplish tasks. "
        "These tools connect to the user's local environment and will execute when called.\n\n"
        "Call format (use this exact format):\n"
        "```function_call\n"
        '{"name": "<tool_name>", "args": {<arguments>}}\n'
        "```\n\n"
        "When calling tools:\n"
        "- Output ONLY the function_call block(s), nothing else\n"
        "- You may call multiple tools with multiple blocks\n"
        "- After receiving a [Tool result for ...], use that data to answer the user\n\n"
        f"Available tools:\n{tool_spec}"
    )


def _google_tool_choice_instruction(req: dict) -> str:
    """Extract tool_choice constraint from Google API toolConfig."""
    tool_config = req.get("toolConfig", {})
    fc_config = tool_config.get("functionCallingConfig", {})
    mode = fc_config.get("mode", "AUTO")
    allowed = fc_config.get("allowedFunctionNames", [])

    if mode == "NONE":
        return "\n\nIMPORTANT: Do NOT call any tools. Respond with text only."
    if mode == "ANY":
        if allowed:
            names = ", ".join(f'"{n}"' for n in allowed)
            return f"\n\nIMPORTANT: You MUST call one of these tools: {names}. Do not respond with text only."
        return "\n\nIMPORTANT: You MUST call at least one tool. Do not respond with text only."
    return ""


def google_contents_to_prompt(req: dict) -> tuple:
    """Convert Google API contents/tools/systemInstruction to (prompt_str, images_list).

    Returns (prompt, images) where images is a list of (bytes, mime_type) tuples.
    """
    parts = []
    images = []

    tool_config = req.get("toolConfig", {})
    fc_mode = tool_config.get("functionCallingConfig", {}).get("mode", "AUTO")

    tools = req.get("tools")
    tool_defs = []
    if tools and fc_mode != "NONE":
        for tool_group in tools:
            for fn in tool_group.get("functionDeclarations", []):
                td = {"name": fn.get("name", ""), "description": fn.get("description", "")}
                params = fn.get("parameters") or fn.get("parametersJsonSchema")
                if params:
                    td["parameters"] = params
                tool_defs.append(td)

    sys_inst = req.get("systemInstruction")
    if sys_inst:
        sys_parts = sys_inst.get("parts", [])
        sys_text = " ".join(p.get("text", "") for p in sys_parts if p.get("text"))
        if sys_text:
            if tool_defs:
                constraint = _google_tool_choice_instruction(req)
                parts.append(sys_text + "\n\n" + build_tool_prompt(tool_defs) + constraint)
            else:
                parts.append(sys_text)
    elif tool_defs:
        constraint = _google_tool_choice_instruction(req)
        parts.append(build_tool_prompt(tool_defs) + constraint)

    for content in req.get("contents", []):
        role = content.get("role", "user")
        msg_parts = []
        for p in content.get("parts", []):
            if p.get("text"):
                msg_parts.append(p["text"])
            elif p.get("inlineData"):
                data = p["inlineData"]
                try:
                    images.append((
                        base64.b64decode(data["data"], validate=True),
                        data.get("mimeType", "image/png"),
                    ))
                    msg_parts.append("[Image attached]")
                except (KeyError, ValueError, TypeError, binascii.Error):
                    pass
            elif p.get("functionCall"):
                fc = p["functionCall"]
                msg_parts.append(
                    f'```function_call\n{json.dumps({"name": fc["name"], "args": fc.get("args", {})}, ensure_ascii=False)}\n```'
                )
            elif p.get("functionResponse"):
                fr = p["functionResponse"]
                msg_parts.append(
                    f'[Tool result for {fr.get("name", "")}]: {json.dumps(fr.get("response", {}), ensure_ascii=False)}'
                )
        text = "\n".join(msg_parts)
        if role == "model":
            parts.append(f"[Assistant]: {text}")
        else:
            parts.append(text)

    return "\n\n".join(p for p in parts if p), images


def parse_google_function_calls(text: str) -> tuple:
    """Extract function_call blocks from model output.

    Handles 3 formats:
    1. ```function_call\\n{...}\\n``` (standard or unclosed)
    2. function_call\\n{...} (without backticks)
    3. Raw JSON with "name" + "args" keys

    Returns (clean_text, [{"name": ..., "args": ...}])
    """
    if not text:
        return "", []
    function_calls = []
    pattern1 = r'```function_call\s*\n(.*?)(?:\n```|$)'
    pattern2 = r'(?:^|\n)function_call\s*\n(\{[^`]*?\})'
    clean = text
    for pattern in [pattern1, pattern2]:
        for match in re.findall(pattern, clean, re.DOTALL):
            data = _repair_json(match.strip())
            if data and isinstance(data, dict) and "name" in data:
                function_calls.append({
                    "name": data["name"],
                    "args": data.get("args", data.get("arguments", {})),
                })
        clean = re.sub(pattern, '', clean, flags=re.DOTALL).strip()
    if not function_calls and clean.strip().startswith("{"):
        data = _repair_json(clean.strip())
        if data and isinstance(data, dict) and "name" in data and ("args" in data or "arguments" in data):
            function_calls.append({
                "name": data["name"],
                "args": data.get("args", data.get("arguments", {})),
            })
            clean = ""
    return clean, function_calls

