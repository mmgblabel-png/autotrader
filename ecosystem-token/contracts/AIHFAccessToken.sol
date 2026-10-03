// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ERC20Permit} from "@openzeppelin/contracts/token/ERC20/extensions/ERC20Permit.sol";

/// @title AI HedgeFund Access Token
/// @notice Fixed-supply utility token intended only for access to AI HedgeFund ecosystem services.
/// @dev No minting, upgrade, blacklist, transfer tax, confiscation, or privileged owner functions exist.
contract AIHFAccessToken is ERC20, ERC20Permit {
    uint256 public constant INITIAL_SUPPLY = 100_000_000 ether;

    error ZeroTreasury();

    constructor(address treasury)
        ERC20("AI HedgeFund Access Token", "AIHF")
        ERC20Permit("AI HedgeFund Access Token")
    {
        if (treasury == address(0)) revert ZeroTreasury();
        _mint(treasury, INITIAL_SUPPLY);
    }
}
