import os

import jwt
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from autotrader.ecosystem import access


@pytest.fixture(autouse=True)
def aihf_env(monkeypatch):
    monkeypatch.setenv("AIHF_SESSION_SECRET", "test-secret-" + "x" * 40)
    monkeypatch.setenv("AIHF_EXPECTED_CHAIN_ID", "80002")
    monkeypatch.setenv("AIHF_ACCESS_VAULT_ADDRESS", "0x0000000000000000000000000000000000001234")
    monkeypatch.setenv("AIHF_SANDBOX_PASS_ISSUANCE_ENABLED", "false")


def test_wallet_challenge_is_one_time_and_recovers_signer():
    wallet = Account.create()
    challenge = access.create_wallet_challenge(wallet.address)
    signed = Account.sign_message(
        encode_defunct(text=challenge["message"]),
        wallet.key,
    )
    result = access.verify_wallet_challenge(
        address=wallet.address,
        nonce=challenge["nonce"],
        message=challenge["message"],
        signature=signed.signature.hex(),
    )
    decoded = access.decode_ecosystem_session(result["access_token"])
    assert decoded["sub"].lower() == wallet.address.lower()
    assert decoded["chain_id"] == 80002

    with pytest.raises(access.EcosystemAuthenticationError):
        access.verify_wallet_challenge(
            address=wallet.address,
            nonce=challenge["nonce"],
            message=challenge["message"],
            signature=signed.signature.hex(),
        )


def test_wallet_challenge_rejects_wrong_signer_without_consuming_nonce():
    expected = Account.create()
    attacker = Account.create()
    challenge = access.create_wallet_challenge(expected.address)
    bad = Account.sign_message(
        encode_defunct(text=challenge["message"]),
        attacker.key,
    )
    with pytest.raises(access.EcosystemAuthenticationError):
        access.verify_wallet_challenge(
            address=expected.address,
            nonce=challenge["nonce"],
            message=challenge["message"],
            signature=bad.signature.hex(),
        )

    good = Account.sign_message(
        encode_defunct(text=challenge["message"]),
        expected.key,
    )
    assert access.verify_wallet_challenge(
        address=expected.address,
        nonce=challenge["nonce"],
        message=challenge["message"],
        signature=good.signature.hex(),
    )["wallet"].lower() == expected.address.lower()


class FakeRpc:
    def __init__(self, tier=2, balance=1000 * 10**18):
        self.tier = tier
        self.balance = balance
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "eth_chainId":
            return hex(80002)
        if method == "eth_getBlockByNumber":
            return {"number": hex(123456)}
        if method == "eth_call":
            data = params[0]["data"]
            tier_selector = "0x" + access.keccak(text="tierOf(address)")[:4].hex()
            if data.startswith(tier_selector):
                return hex(self.tier)
            return hex(self.balance)
        raise AssertionError(method)


def test_entitlement_snapshot_uses_safe_block_and_canonical_vault():
    rpc = FakeRpc(tier=2)
    wallet = Account.create().address
    snapshot = access.EntitlementService(rpc=rpc).snapshot(wallet)
    assert snapshot["tier"] == "PRO"
    assert snapshot["active_locked_aihf"] == "1000"
    assert snapshot["block_number"] == 123456
    eth_calls = [params for method, params in rpc.calls if method == "eth_call"]
    assert eth_calls
    assert all(params[1] == hex(123456) for params in eth_calls)


def test_entitlement_fails_closed_on_wrong_chain():
    class WrongChain(FakeRpc):
        def call(self, method, params):
            if method == "eth_chainId":
                return hex(137)
            return super().call(method, params)

    with pytest.raises(access.EcosystemRpcError):
        access.EntitlementService(rpc=WrongChain()).snapshot(Account.create().address)


def test_sandbox_claim_is_dry_run_and_does_not_pretend_to_mint(monkeypatch):
    snapshot = {
        "wallet": Account.create().address,
        "tier": "QUANT",
        "tier_rank": 3,
    }
    claim = access.sandbox_pass_claim(snapshot)
    assert claim["eligible"] is True
    assert claim["minted"] is False
    assert claim["transaction_hash"] is None
    assert claim["status"] == "dry_run"
    assert claim["claimable"] is False


def test_founder_and_sandbox_config_hard_boundaries():
    config = access.load_sandbox_hq_config()
    assert config["economics"]["autotrader_live_capital_allowed"] is False
    assert config["economics"]["pay_to_win"] is False
    denied = set(config["founder_key"]["does_not_grant"])
    assert "pro_research_without_pro_entitlement" in denied
    assert "quant_research_without_quant_entitlement" in denied
