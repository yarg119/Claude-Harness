import re

from claude_harness import vendor


def frontmatter_name(text: str) -> str:
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    assert m, "missing frontmatter"
    n = re.search(r"^name:\s*(\S+)\s*$", m.group(1), re.M)
    assert n, "frontmatter has no name"
    return n.group(1)


def test_every_vendored_skill_is_present_pinned_and_named():
    for e in vendor.load_manifest():
        d = vendor.skill_dir(e)
        skill = (d / "SKILL.md").read_text()
        assert frontmatter_name(skill) == e["name"]
        src = (d / "SOURCE.md").read_text()
        assert e["ref"] in src and e["repo"] in src and e["license"] in src
        assert len(e["ref"]) == 40
        lic = (d / "LICENSE").read_text()   # the upstream notice must ship with the copy (public repo)
        assert "Copyright" in lic
        if e["license"] == "MIT":
            assert "Permission is hereby granted" in lic


def test_command_to_skill_transform_keeps_rules_and_replaces_frontmatter():
    cmd = "---\ndescription: x\nargument-hint: <f>\n---\n\n# Web Interface Guidelines\n\nReview these files: $ARGUMENTS\n- rule one\n"
    out = vendor.transform({"transform": "command-to-skill"}, cmd)
    assert frontmatter_name(out) == "web-interface-guidelines"
    assert "argument-hint: <file-or-pattern>" in out.split("---")[1]
    assert out.endswith("# Web Interface Guidelines\n\nReview these files: $ARGUMENTS\n- rule one\n")
    assert "description: x" not in out


def test_ui_check_skill_frontmatter():
    from claude_harness import paths
    text = (paths.REPO_CLAUDE / "skills" / "ui-check" / "SKILL.md").read_text()
    assert frontmatter_name(text) == "ui-check" and "playwright-cli" in text and "web-interface-guidelines" in text
