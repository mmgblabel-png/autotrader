// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {IERC20Permit} from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Permit.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @title AI HedgeFund Access Vault
/// @notice Non-yielding token lock used to prove service-access tiers.
/// @dev Pending unlocks stop counting toward access immediately. No admin, rewards, upgrades, or sweep exists.
contract AIHFAccessVault is ReentrancyGuard {
    using SafeERC20 for IERC20;

    enum Tier { NONE, READER, PRO, QUANT }

    struct PendingUnlock {
        uint256 amount;
        uint48 executableAt;
    }

    IERC20 public immutable token;
    uint256 public immutable readerThreshold;
    uint256 public immutable proThreshold;
    uint256 public immutable quantThreshold;
    uint48 public immutable unlockCooldown;

    uint256 public totalLocked;
    mapping(address => uint256) public lockedBalance;
    mapping(address => PendingUnlock) public pendingUnlock;

    error ZeroAddress();
    error InvalidThresholds();
    error InvalidCooldown();
    error ZeroAmount();
    error UnlockAlreadyPending();
    error NoPendingUnlock();
    error InsufficientLockedBalance();
    error UnlockCooldownActive(uint48 executableAt);

    event Locked(address indexed account, uint256 amount, uint256 newLockedBalance);
    event UnlockRequested(address indexed account, uint256 amount, uint48 executableAt);
    event UnlockCancelled(address indexed account, uint256 amount);
    event Unlocked(address indexed account, uint256 amount, uint256 newLockedBalance);

    constructor(
        address tokenAddress,
        uint256 readerThreshold_,
        uint256 proThreshold_,
        uint256 quantThreshold_,
        uint48 unlockCooldown_
    ) {
        if (tokenAddress == address(0)) revert ZeroAddress();
        if (
            readerThreshold_ == 0 ||
            readerThreshold_ >= proThreshold_ ||
            proThreshold_ >= quantThreshold_
        ) revert InvalidThresholds();
        if (unlockCooldown_ < 1 days || unlockCooldown_ > 30 days) revert InvalidCooldown();

        token = IERC20(tokenAddress);
        readerThreshold = readerThreshold_;
        proThreshold = proThreshold_;
        quantThreshold = quantThreshold_;
        unlockCooldown = unlockCooldown_;
    }

    function lock(uint256 amount) external nonReentrant {
        _lock(msg.sender, amount);
    }

    function lockWithPermit(
        uint256 amount,
        uint256 permitDeadline,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external nonReentrant {
        IERC20Permit(address(token)).permit(
            msg.sender, address(this), amount, permitDeadline, v, r, s
        );
        _lock(msg.sender, amount);
    }

    function requestUnlock(uint256 amount) external {
        if (amount == 0) revert ZeroAmount();
        if (pendingUnlock[msg.sender].amount != 0) revert UnlockAlreadyPending();
        if (amount > lockedBalance[msg.sender]) revert InsufficientLockedBalance();

        uint48 executableAt = uint48(block.timestamp) + unlockCooldown;
        pendingUnlock[msg.sender] = PendingUnlock(amount, executableAt);
        emit UnlockRequested(msg.sender, amount, executableAt);
    }

    function cancelUnlock() external {
        PendingUnlock memory request = pendingUnlock[msg.sender];
        if (request.amount == 0) revert NoPendingUnlock();

        delete pendingUnlock[msg.sender];
        emit UnlockCancelled(msg.sender, request.amount);
    }

    function executeUnlock() external nonReentrant {
        PendingUnlock memory request = pendingUnlock[msg.sender];
        if (request.amount == 0) revert NoPendingUnlock();
        if (block.timestamp < request.executableAt) {
            revert UnlockCooldownActive(request.executableAt);
        }

        delete pendingUnlock[msg.sender];
        lockedBalance[msg.sender] -= request.amount;
        totalLocked -= request.amount;
        token.safeTransfer(msg.sender, request.amount);

        emit Unlocked(msg.sender, request.amount, lockedBalance[msg.sender]);
    }

    function activeLockedBalance(address account) public view returns (uint256) {
        return lockedBalance[account] - pendingUnlock[account].amount;
    }

    function tierOf(address account) public view returns (Tier) {
        uint256 active = activeLockedBalance(account);
        if (active >= quantThreshold) return Tier.QUANT;
        if (active >= proThreshold) return Tier.PRO;
        if (active >= readerThreshold) return Tier.READER;
        return Tier.NONE;
    }

    function _lock(address account, uint256 amount) private {
        if (amount == 0) revert ZeroAmount();

        token.safeTransferFrom(account, address(this), amount);
        lockedBalance[account] += amount;
        totalLocked += amount;

        emit Locked(account, amount, lockedBalance[account]);
    }
}
