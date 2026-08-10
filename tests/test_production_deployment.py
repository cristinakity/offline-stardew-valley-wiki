from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_deployment_uses_broker_without_direct_host_access() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy-production.yml").read_text(encoding="utf-8")
    assert "/api/deployments/" in workflow
    assert "id-token: write" in workflow
    assert "BROKER_PERSISTENT_DATA_READY" in workflow
    lowered = workflow.casefold()
    for forbidden in ("rack" + "nerd", "v" + "ps", "s" + "sh", "s" + "cp"):
        assert forbidden not in lowered


def test_production_files_use_generic_names() -> None:
    paths = [
        ROOT / "compose.production.yml",
        ROOT / "docs" / "production-deployment.md",
        ROOT / "readme.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths).casefold()
    assert "rack" + "nerd" not in combined
    assert "v" + "ps" not in combined
    assert not (ROOT / ("compose." + "v" + "ps.yml")).exists()
    assert not (ROOT / "docs" / ("v" + "ps-deployment.md")).exists()
