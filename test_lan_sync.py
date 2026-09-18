import json

from lan_sync import LanSyncServer, build_sync_url, sync_with_peer


def _sample(value: str) -> bytes:
    return json.dumps({"schema_version": 1, "records": [{"id": value}]}).encode()


def test_build_sync_url_rejects_public_ip():
    try:
        build_sync_url("8.8.8.8:1234", "123456")
    except ValueError as exc:
        assert "局域网" in str(exc)
    else:
        raise AssertionError("public IP should be rejected")


def test_lan_roundtrip():
    state = {"payload": _sample("server")}

    def get_backup():
        return state["payload"]

    def merge_backup(raw: bytes):
        incoming = json.loads(raw.decode())
        state["payload"] = json.dumps({
            "schema_version": 1,
            "records": [{"id": "server"}, *incoming["records"]],
        }).encode()
        return state["payload"]

    server = LanSyncServer(get_backup, merge_backup)
    server.host_ip = "127.0.0.1"
    server.start()
    try:
        merged = sync_with_peer(server.address, server.pair_code, _sample("client"))
        ids = [x["id"] for x in json.loads(merged.decode())["records"]]
        assert ids == ["server", "client"]
    finally:
        server.stop()
