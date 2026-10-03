# Operations policy

## Wallet roles

### Deployer
- disposable on testnet;
- dedicated hardware-backed signer procedure for mainnet;
- does not hold operating treasury after deployment.

### Treasury
- Safe multisig;
- target launch policy: 2-of-3 independent owners;
- no signer key stored in AutoTrader, Railway, GitHub or frontend code;
- all material transfers annotated in treasury records.

### Vesting beneficiaries
- receive team/contributor allocations only through vesting wallets;
- no direct unlocked team allocation at launch.

### Application wallet
- none required for entitlement reads;
- backend verifies user signatures but never has custody of user AIHF.

## Treasury controls

- AIHF allocation transfers require documented purpose.
- Any mainnet liquidity action requires separate budget approval and legal gate.
- Treasury must never fund AutoTrader positions or be represented as fund capital.
- AutoTrader bankroll must never fund token liquidity or token marketing.
- No undisclosed market-support trades.

## Incident priorities

1. protect users and stop unsafe product actions;
2. preserve evidence/logs;
3. disclose material contract/service incidents appropriately;
4. never bypass multisig or vesting to move faster;
5. if the immutable contract is materially defective, prepare a clean migration plan rather than adding a hidden control path.

## Monitoring

Track:
- token/vault/vesting contract events;
- anomalous lock/unlock spikes;
- treasury Safe transactions;
- entitlement RPC failures;
- API authentication failures/replay attempts;
- contract address/chain-ID mismatches;
- published document/version hashes.

Monitoring may alert operators but must not grant the monitoring service a treasury signing key.
