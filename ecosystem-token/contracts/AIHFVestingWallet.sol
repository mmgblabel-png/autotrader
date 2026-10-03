// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {VestingWallet} from "@openzeppelin/contracts/finance/VestingWallet.sol";
import {VestingWalletCliff} from "@openzeppelin/contracts/finance/VestingWalletCliff.sol";

/// @title AIHF Vesting Wallet
/// @notice Standard 48-month linear vesting schedule with an explicit cliff.
/// @dev A 12-month cliff produces the conventional four-year schedule:
///      nothing before month 12, catch-up vesting at the cliff, then linear vesting to month 48.
contract AIHFVestingWallet is VestingWalletCliff {
    constructor(
        address beneficiary,
        uint64 startTimestamp,
        uint64 durationSeconds,
        uint64 cliffSeconds
    )
        VestingWallet(beneficiary, startTimestamp, durationSeconds)
        VestingWalletCliff(cliffSeconds)
    {}
}
