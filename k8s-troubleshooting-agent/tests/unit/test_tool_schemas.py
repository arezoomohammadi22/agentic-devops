from app.tool_schemas import build_tool_schemas


def test_tool_schemas_never_expose_namespace_argument():
    tools = build_tool_schemas(enable_pv_lookup=False)
    serialized = repr(tools).lower()
    assert '"namespace"' not in serialized
    assert "'namespace'" not in serialized


def test_pv_tool_is_absent_by_default():
    names = {tool["name"] for tool in build_tool_schemas(enable_pv_lookup=False)}
    assert "list_persistent_volumes_for_namespace" not in names


def test_pv_tool_is_present_only_when_explicitly_enabled():
    names = {tool["name"] for tool in build_tool_schemas(enable_pv_lookup=True)}
    assert "list_persistent_volumes_for_namespace" in names
