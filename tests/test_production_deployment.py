from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_deployment_uses_broker_without_direct_host_access() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy-production.yml").read_text(encoding="utf-8")
    assert "/api/deployments/" in workflow
    assert "id-token: write" in workflow
    assert "BROKER_PERSISTENT_DATA_READY" in workflow
    assert "runtime_env" in workflow
    assert "content-lock.json" in workflow
    assert "steps.image.outputs.digest" in workflow
    lowered = workflow.casefold()
    for forbidden in ("rack" + "nerd", "v" + "ps", "s" + "sh", "s" + "cp"):
        assert forbidden not in lowered


def test_production_deployment_is_split_into_dependent_stages() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy-production.yml").read_text(encoding="utf-8")
    assert "  validate_release:" in workflow
    assert "  build_image:" in workflow
    assert "    needs: validate_release" in workflow
    assert "  deploy_production:" in workflow
    assert "    needs: [validate_release, build_image]" in workflow
    assert "IMAGE_DIGEST: ${{ needs.build_image.outputs.image_digest }}" in workflow
    assert "SNAPSHOT_REF: ${{ needs.validate_release.outputs.snapshot_ref }}" in workflow


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


def test_content_lock_blocks_deploy_until_publication() -> None:
    lock = (ROOT / "content-lock.json").read_text(encoding="utf-8")
    assert '"version": "v1.3.0"' in lock
    assert '"snapshot_id": "20260811T015121Z-7206e5e0cacc"' in lock
    assert '"oci_ref": null' in lock or "@sha256:" in lock


def test_rollback_uses_immutable_image_and_broker() -> None:
    workflow = (ROOT / ".github" / "workflows" / "rollback-production.yml").read_text()
    assert "@sha256:" in workflow
    assert "/api/deployments/" in workflow
    assert "runtime_env" in workflow
    assert "id-token: write" in workflow
