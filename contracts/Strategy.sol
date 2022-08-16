// SPDX-License-Identifier: AGPL-3.0

pragma solidity ^0.8.12;

import {BaseStrategy} from "@yearn/yearn-vaults/contracts/BaseStrategy.sol";

import {Address} from "@openzeppelin/contracts/utils/Address.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {
    SafeERC20
} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

import "@openzeppelin/contracts/utils/math/Math.sol";

//import "../interfaces/uniswap/IUni.sol";
import "../interfaces/velodrome/IVelodromeRouter.sol";

import "../interfaces/aave/v3/core/IPoolDataProvider.sol";
import "../interfaces/aave/v3/core/IAToken.sol";
import "../interfaces/aave/v3/core/IVariableDebtToken.sol";
import "../interfaces/aave/v3/core/IPool.sol";
import "../interfaces/aave/v3/core/IPoolAddressesProvider.sol";
import "../interfaces/aave/v3/core/DataTypes.sol";
import "../interfaces/aave/v3/core/IFlashLoanReceiver.sol";
import "../interfaces/aave/v3/periphery/IRewardsController.sol";

import "./ySwapper.sol";

contract Strategy is BaseStrategy, IFlashLoanReceiver, ySwapper {
    using Address for address;
    using SafeERC20 for IERC20;

    // protocol address
    IPoolDataProvider private constant protocolDataProvider =
        IPoolDataProvider(0x69FA688f1Dc47d4B5d8029D5a35FB7a548310654);
    IRewardsController private constant rewardsController =
        IRewardsController(0x929EC64c34a17401F460460D4B9390518E5B473e);

    IPool public constant POOL =
        IPool(0x794a61358D6845594F94dc1DB02A252b5b4814aD);
    IPoolAddressesProvider public constant ADDRESSES_PROVIDER =
        IPoolAddressesProvider(0xa97684ead0e402dC232d5A977953DF7ECBaB3CDb);

    // weth
    address private constant weth = 0x4200000000000000000000000000000000000006;
    // usdc
    address private constant usdc = 0x7F5c764cBc14f9669B88837ca1490cCa17c31607;

    // Supply and borrow tokens
    IAToken public aToken;
    IVariableDebtToken public debtToken;
    address[] private rewardTokens;

    // SWAP routers
    IVelodromeRouter public constant VELODROME_ROUTER =
        IVelodromeRouter(0xa132DAB612dB5cB9fC9Ac426A0Cc215A3423F9c9);

    // OPS State Variables
    uint256 private constant DEFAULT_COLLAT_TARGET_MARGIN = 0.02 ether;
    uint256 private constant DEFAULT_COLLAT_MAX_MARGIN = 0.005 ether;
    uint256 private constant LIQUIDATION_WARNING_THRESHOLD = 0.01 ether;

    uint256 public maxBorrowCollatRatio; // The maximum the protocol will let us borrow
    uint256 public targetCollatRatio; // The LTV we are levering up to
    uint256 public maxCollatRatio; // Closest to liquidation we'll risk

    uint256 public minWant;
    uint256 public minRatio;
    uint256 public minRewardToSell;

    bool public veloUseUsdcIntermediate; // use weth by default
    bool public veloWantIsStable; // tell velo hop from usdc to want is stable

    uint8 public maxIterations;
    bool public flashloanEnabled;

    bool private alreadyAdjusted; // Signal whether a position adjust was done in prepareReturn

    uint16 private constant referral = 0;

    uint256 private constant MAX_BPS = 1e4;
    uint256 private constant WAD_BPS_RATIO = 1e14;
    uint256 private constant COLLATERAL_RATIO_PRECISION = 1 ether;
    uint256 private constant PESSIMISM_FACTOR = 1000;
    uint256 private DECIMALS;

    constructor(address _vault) BaseStrategy(_vault) {
        _initializeThis();
    }

    function initialize(
        address _vault,
        address _strategist,
        address _rewards,
        address _keeper
    ) external {
        _initialize(_vault, _strategist, _rewards, _keeper);
        _initializeThis();
    }

    function _initializeThis() internal {
        // initialize operational state
        maxIterations = 15;
        flashloanEnabled = true;

        // mins
        minWant = 10000;
        minRatio = 0.005 ether;
        minRewardToSell = 1e15;

        veloUseUsdcIntermediate = true;

        alreadyAdjusted = false;

        // Set lending+borrowing tokens
        (address _aToken, , address _debtToken) =
            protocolDataProvider.getReserveTokensAddresses(address(want));
        require(_aToken != address(0));
        aToken = IAToken(_aToken);
        debtToken = IVariableDebtToken(_debtToken);

        _setEMode(true); // use emode if it's available
        // Set collateral targets
        _autoConfigureLTVs();

        DECIMALS = 10**vault.decimals();

        // approve spend protocol spend
        approveMaxSpend(address(want), address(POOL));
        approveMaxSpend(address(aToken), address(POOL));

        _updateRewardTokens();
        // approve swap router spend
        approveRouterRewardSpend();
    }

    // SETTERS
    function setCollateralTargets(
        uint256 _targetCollatRatio,
        uint256 _maxCollatRatio,
        uint256 _maxBorrowCollatRatio
    ) external onlyVaultManagers {
        (uint256 ltv, uint256 liquidationThreshold) = getProtocolCollatRatios();
        require(_targetCollatRatio < liquidationThreshold);
        require(_maxCollatRatio < liquidationThreshold);
        require(_targetCollatRatio < _maxCollatRatio);
        require(_maxBorrowCollatRatio < ltv);

        targetCollatRatio = _targetCollatRatio;
        maxCollatRatio = _maxCollatRatio;
        maxBorrowCollatRatio = _maxBorrowCollatRatio;
    }

    function setMinsAndMaxs(
        uint256 _minWant,
        uint256 _minRatio,
        uint8 _maxIterations
    ) external onlyVaultManagers {
        require(_minRatio < maxBorrowCollatRatio);
        require(_maxIterations > 0 && _maxIterations < 16);
        minWant = _minWant;
        minRatio = _minRatio;
        maxIterations = _maxIterations;
    }

    function setFlashloanEnabled(bool _enableFlashloan)
        external
        onlyVaultManagers
    {
        flashloanEnabled = _enableFlashloan;
    }

    function setEMode(bool _enableEmode, bool _autosetLTVs)
        external
        onlyVaultManagers
    {
        _setEMode(_enableEmode);
        if (_autosetLTVs) {
            _autoConfigureLTVs();
        } else {
            (uint256 ltv, uint256 liquidationThreshold) =
                getProtocolCollatRatios();
            require(targetCollatRatio < liquidationThreshold);
            require(maxCollatRatio < liquidationThreshold);
            require(maxBorrowCollatRatio < ltv);
        }
    }

    function setRewardBehavior(
        uint256 _minRewardToSell,
        bool _veloUseUsdcIntermediate,
        bool _veloWantIsStable
    ) external onlyVaultManagers {
        minRewardToSell = _minRewardToSell;
        veloUseUsdcIntermediate = _veloUseUsdcIntermediate;
        veloWantIsStable = _veloWantIsStable;
    }

    function name() external view override returns (string memory) {
        return "StrategyGenLevAaveV3-Optimism";
    }

    function estimatedTotalAssets() public view override returns (uint256) {
        uint256 balanceExcludingRewards = balanceOfWant() + getCurrentSupply();

        // if we don't have a position, don't worry about rewards
        if (balanceExcludingRewards < minWant) {
            return balanceExcludingRewards;
        }

        uint256 rewards =
            (estimatedRewardsInWant() * (MAX_BPS - PESSIMISM_FACTOR)) / MAX_BPS;
        return balanceExcludingRewards + rewards;
    }

    function estimatedRewardsInWant()
        public
        view
        returns (uint256 rewardBalanceInWant)
    {
        address[] memory assets = getAssets();
        IRewardsController _rewardsController = rewardsController;

        for (uint256 i; i < rewardTokens.length; ++i) {
            uint256 rewardBalance =
                _rewardsController.getUserRewards(
                    assets,
                    address(this),
                    rewardTokens[i]
                );
            rewardBalance += IERC20(rewardTokens[i]).balanceOf(address(this));
            rewardBalanceInWant += tokenToWant(rewardTokens[i], rewardBalance);
        }
    }

    function prepareReturn(uint256 _debtOutstanding)
        internal
        override
        returns (
            uint256 _profit,
            uint256 _loss,
            uint256 _debtPayment
        )
    {
        // claim & sell rewards
        _claimRewards();
        _sellRewards();

        // account for profit / losses
        uint256 totalDebt = vault.strategies(address(this)).totalDebt;

        uint256 _balanceOfWant = balanceOfWant();

        // Assets immediately convertable to want only
        uint256 supply = getCurrentSupply();
        uint256 totalAssets = _balanceOfWant + supply;

        unchecked {
            if (totalDebt > totalAssets) {
                // we have losses
                _loss = totalDebt - totalAssets;
            } else {
                // we have profit
                _profit = totalAssets - totalDebt;
            }
        }

        // free funds to repay debt + profit to the strategy
        uint256 amountAvailable = _balanceOfWant;
        uint256 amountRequired = _debtOutstanding + _profit;

        if (_debtOutstanding != 0 && amountRequired > amountAvailable) {
            // we need to free funds
            // we dismiss losses here, they cannot be generated from withdrawal
            // but it is possible for the strategy to unwind full position
            (amountAvailable, ) = liquidatePosition(amountRequired);

            // Don't do a redundant adjustment in adjustPosition
            alreadyAdjusted = true;

            if (amountAvailable >= amountRequired) {
                _debtPayment = _debtOutstanding;
            } else {
                // we were not able to free enough funds
                if (amountAvailable < _debtOutstanding) {
                    // available funds are lower than the repayment that we need to do
                    _profit = 0;
                    _debtPayment = amountAvailable;
                    // we dont report losses here as the strategy might not be able to return in this harvest
                    // but it will still be there for the next harvest
                } else {
                    // NOTE: amountRequired is always equal or greater than _debtOutstanding
                    // important to use amountRequired just in case amountAvailable is > amountAvailable
                    _debtPayment = _debtOutstanding;
                    _profit = amountAvailable - _debtPayment;
                }
            }
        } else {
            _debtPayment = _debtOutstanding;
        }
    }

    function adjustPosition(uint256 _debtOutstanding) internal override {
        if (alreadyAdjusted) {
            alreadyAdjusted = false; // reset for next time
            return;
        }

        uint256 wantBalance = balanceOfWant();
        // deposit available want as collateral
        if (
            wantBalance > _debtOutstanding &&
            wantBalance - _debtOutstanding > minWant
        ) {
            uint256 amountToDeposit = wantBalance - _debtOutstanding;
            _depositCollateral(amountToDeposit);
            // we update the value
            wantBalance = _debtOutstanding;
        }
        // check current position
        uint256 currentCollatRatio = getCurrentCollatRatio();

        // Either we need to free some funds OR we want to be max levered
        if (_debtOutstanding > wantBalance) {
            // we should free funds
            uint256 amountRequired = _debtOutstanding - wantBalance;

            // NOTE: vault will take free funds during the next harvest
            _freeFunds(amountRequired);
        } else if (currentCollatRatio < targetCollatRatio) {
            // we should lever up
            if (targetCollatRatio - currentCollatRatio > minRatio) {
                // we only act on relevant differences
                _leverMax();
            }
        } else if (currentCollatRatio > targetCollatRatio) {
            if (currentCollatRatio - targetCollatRatio > minRatio) {
                (uint256 deposits, uint256 borrows) = getCurrentPosition();
                uint256 newBorrow =
                    getBorrowFromSupply(deposits - borrows, targetCollatRatio);
                _leverDownTo(newBorrow, borrows);
            }
        }
    }

    function liquidatePosition(uint256 _amountNeeded)
        internal
        override
        returns (uint256 _liquidatedAmount, uint256 _loss)
    {
        // NOTE: Maintain invariant `want.balanceOf(this) >= _liquidatedAmount`
        // NOTE: Maintain invariant `_liquidatedAmount + _loss <= _amountNeeded`
        uint256 wantBalance = balanceOfWant();
        if (wantBalance > _amountNeeded) {
            // if there is enough free want, let's use it
            return (_amountNeeded, 0);
        }

        // we need to free funds
        uint256 amountRequired = _amountNeeded - wantBalance;
        _freeFunds(amountRequired);

        uint256 freeAssets = balanceOfWant();
        if (_amountNeeded > freeAssets) {
            _liquidatedAmount = freeAssets;
            uint256 diff = _amountNeeded - _liquidatedAmount;
            if (diff <= minWant) {
                _loss = diff;
            }
        } else {
            _liquidatedAmount = _amountNeeded;
        }
    }

    function tendTrigger(uint256 gasCost) public view override returns (bool) {
        if (harvestTrigger(gasCost)) {
            //harvest takes priority
            return false;
        }
        // pull the liquidation liquidationThreshold from protocol to be extra safu
        (, uint256 liquidationThreshold) = getProtocolCollatRatios();

        uint256 currentCollatRatio = getCurrentCollatRatio();

        if (currentCollatRatio >= liquidationThreshold) {
            return true;
        }

        return (liquidationThreshold - currentCollatRatio <=
            LIQUIDATION_WARNING_THRESHOLD);
    }

    function liquidateAllPositions()
        internal
        override
        returns (uint256 _amountFreed)
    {
        (_amountFreed, ) = liquidatePosition(type(uint256).max);
    }

    function prepareMigration(address _newStrategy) internal override {
        require(getCurrentSupply() < minWant);
    }

    function protectedTokens()
        internal
        view
        override
        returns (address[] memory)
    {}

    //emergency function that we can use to deleverage manually if something is broken
    function manualDeleverage(uint256 amount, bool withATokens)
        external
        onlyVaultManagers
    {
        if (withATokens) {
            _repayWithATokens(amount);
        } else {
            _withdrawCollateral(amount);
            _repayWant(amount);
        }
    }

    //emergency function that we can use to deleverage manually if something is broken
    function manualReleaseWant(uint256 amount) external onlyVaultManagers {
        _withdrawCollateral(amount);
    }

    // function that we can use to claim rewards if something is broken
    function manualClaimRewards() external onlyVaultManagers {
        _claimRewards();
    }

    // function that we can use to sell rewards if something is broken
    function manualSellRewards() external onlyVaultManagers {
        _sellRewards();
    }

    function updateRewardTokens() external onlyVaultManagers {
        _updateRewardTokens();
        approveRouterRewardSpend();
    }

    // INTERNAL ACTIONS

    function _claimRewards() internal returns (uint256) {
        IRewardsController _rewardsController = rewardsController;
        _rewardsController.claimAllRewards(getAssets(), address(this));
    }

    function _sellRewards() internal returns (uint256) {
        // sell reward for want
        for (uint256 i; i < rewardTokens.length; ++i) {
            uint256 rewardBalance =
                IERC20(rewardTokens[i]).balanceOf(address(this));
            if (rewardBalance >= minRewardToSell) {
                _sellTokenForWant(rewardTokens[i], rewardBalance, 0);
            }
        }
    }

    function _freeFunds(uint256 amountToFree) internal returns (uint256) {
        if (amountToFree == 0) return 0;

        (uint256 deposits, uint256 borrows) = getCurrentPosition();

        uint256 realAssets = deposits - borrows;
        uint256 amountRequired = Math.min(amountToFree, realAssets);
        uint256 newSupply = realAssets - amountRequired;
        uint256 newBorrow = getBorrowFromSupply(newSupply, targetCollatRatio);

        // repay required amount
        _leverDownTo(newBorrow, borrows);

        return balanceOfWant();
    }

    function _leverMax() internal {
        (uint256 deposits, uint256 borrows) = getCurrentPosition();
        uint256 wantBalance = balanceOfWant();

        uint256 realSupply = deposits - borrows + wantBalance;
        uint256 newBorrow = getBorrowFromSupply(realSupply, targetCollatRatio);
        uint256 totalAmountToBorrow = newBorrow - borrows;

        uint8 _maxIterations = maxIterations;
        uint256 _minWant = minWant;

        if (flashloanEnabled) {
            _flashloan(totalAmountToBorrow);
        } else {
            for (
                uint8 i = 0;
                i < _maxIterations && totalAmountToBorrow > _minWant;
                i++
            ) {
                uint256 amount = totalAmountToBorrow;

                // calculate how much borrow to take
                //(deposits, borrows) = getCurrentPosition();
                uint256 canBorrow =
                    getBorrowFromDeposit(
                        deposits + wantBalance,
                        maxBorrowCollatRatio
                    );

                if (canBorrow <= borrows) {
                    break;
                }
                canBorrow = canBorrow - borrows;

                if (canBorrow < amount) {
                    amount = canBorrow;
                }

                // deposit available want as collateral
                _depositCollateral(wantBalance);

                // borrow available amount
                _borrowWant(amount);

                (deposits, borrows) = getCurrentPosition();
                wantBalance = balanceOfWant();

                totalAmountToBorrow = totalAmountToBorrow - amount;
            }
        }

        if (wantBalance >= minWant) {
            _depositCollateral(wantBalance);
        }
    }

    function _leverDownTo(uint256 newAmountBorrowed, uint256 currentBorrowed)
        internal
    {
        if (currentBorrowed > newAmountBorrowed) {
            uint256 wantBalance = balanceOfWant();
            uint256 totalRepayAmount = currentBorrowed - newAmountBorrowed;
            uint256 _maxCollatRatio = maxCollatRatio;
            _repayWithATokens(
                totalRepayAmount < currentBorrowed
                    ? totalRepayAmount
                    : type(uint256).max
            );
        }

        (uint256 deposits, uint256 borrows) = getCurrentPosition();
        // deposit back to get targetCollatRatio (we always need to leave this in this ratio)
        uint256 _targetCollatRatio = targetCollatRatio;
        uint256 targetDeposit =
            getDepositFromBorrow(borrows, _targetCollatRatio);
        if (targetDeposit > deposits) {
            uint256 toDeposit = targetDeposit - deposits;
            if (toDeposit > minWant) {
                _depositCollateral(Math.min(toDeposit, balanceOfWant()));
            }
        } else {
            _withdrawExcessCollateral(_targetCollatRatio, deposits, borrows);
        }
    }

    function _withdrawExcessCollateral(
        uint256 collatRatio,
        uint256 deposits,
        uint256 borrows
    ) internal returns (uint256 amount) {
        uint256 theoDeposits = getDepositFromBorrow(borrows, collatRatio);
        if (deposits > theoDeposits) {
            uint256 toWithdraw = deposits - theoDeposits;
            return _withdrawCollateral(toWithdraw);
        }
    }

    function _depositCollateral(uint256 amount) internal {
        if (amount == 0) return;
        POOL.supply(address(want), amount, address(this), referral);
    }

    function _borrowWant(uint256 amount) internal {
        if (amount == 0) return;
        POOL.borrow(address(want), amount, 2, referral, address(this));
    }

    function _withdrawCollateral(uint256 amount) internal returns (uint256) {
        if (amount == 0) return 0;
        return POOL.withdraw(address(want), amount, address(this));
    }

    function _repayWant(uint256 amount) internal returns (uint256) {
        if (amount == 0) return 0;
        return POOL.repay(address(want), amount, 2, address(this));
    }

    function _repayWithATokens(uint256 amount) internal returns (uint256) {
        if (amount == 0) return 0;
        return POOL.repayWithATokens(address(want), amount, 2);
    }

    function _flashloan(uint256 amount) internal {
        if (amount == 0) return;
        address[] memory tokens = new address[](1);
        tokens[0] = address(want);
        uint256[] memory amounts = new uint256[](1);
        amounts[0] = amount;
        uint256[] memory modes = new uint256[](1);
        modes[0] = 2;
        POOL.flashLoan(
            address(this),
            tokens,
            amounts,
            modes,
            address(this),
            "",
            referral
        );
    }

    function _setEMode(bool _enableEmode) internal {
        uint8 _emodeCategory =
            uint8(protocolDataProvider.getReserveEModeCategory(address(want)));
        if (_emodeCategory == 0) return;
        POOL.setUserEMode(_enableEmode ? _emodeCategory : 0);
    }

    // Section: flashloan callback

    function executeOperation(
        address[] calldata assets,
        uint256[] calldata amounts,
        uint256[] calldata premiums,
        address initiator,
        bytes calldata params
    ) external returns (bool) {
        require(initiator == address(this)); // dev: initiator must be this strategy
        require(assets[0] == address(want)); // dev: loan asset must be want
        require(amounts.length == 1);
        uint256 amount = amounts[0];
        _depositCollateral(balanceOfWant());
        return true;
    }

    // Section: interal balanceOf views

    function balanceOfWant() internal view returns (uint256) {
        return want.balanceOf(address(this));
    }

    function balanceOfAToken() internal view returns (uint256) {
        return aToken.balanceOf(address(this));
    }

    function balanceOfDebtToken() internal view returns (uint256) {
        return IERC20(address(debtToken)).balanceOf(address(this));
    }

    // Section: Current Position Views

    function getCurrentPosition()
        public
        view
        returns (uint256 deposits, uint256 borrows)
    {
        deposits = balanceOfAToken();
        borrows = balanceOfDebtToken();
    }

    function getCurrentCollatRatio()
        public
        view
        returns (uint256 currentCollatRatio)
    {
        (uint256 deposits, uint256 borrows) = getCurrentPosition();

        if (deposits > 0) {
            currentCollatRatio =
                (borrows * COLLATERAL_RATIO_PRECISION) /
                deposits;
        }
    }

    function getCurrentSupply() public view returns (uint256) {
        (uint256 deposits, uint256 borrows) = getCurrentPosition();
        return deposits - borrows;
    }

    function getEmodeEnabled() public view returns (bool) {
        uint256 _emodeCategory = POOL.getUserEMode(address(this));
        return _emodeCategory != 0;
    }

    function getRewardTokens()
        external
        view
        returns (address[] memory _rewardTokens)
    {
        return rewardTokens;
    }

    // Section: yswaps

    function getYSwapTokens()
        internal
        view
        override
        returns (address[] memory swapFrom, address[] memory swapTo)
    {
        swapFrom = rewardTokens;
        swapTo = new address[](swapFrom.length);
        for (uint256 i; i < swapTo.length; ++i) {
            swapTo[i] = address(want);
        }
    }

    function removeTradeFactoryPermissions()
        external
        override
        onlyVaultManagers
    {
        _removeTradeFactory();
    }

    function updateTradeFactoryPermissions(address _tradeFactory)
        external
        override
        onlyGovernance
    {
        _updateTradeFactory(_tradeFactory);
    }

    // Section: swap helpers

    function tokenToWant(address token, uint256 amountIn)
        internal
        view
        returns (uint256 amountOut)
    {
        if (amountIn == 0 || address(want) == token) {
            return amountIn;
        }

        uint256[] memory amounts =
            VELODROME_ROUTER.getAmountsOut(
                amountIn,
                getTokenOutPathVelo(token, address(want))
            );
        amountOut = amounts[amounts.length - 1];
    }

    function ethToWant(uint256 _amtInWei)
        public
        view
        override
        returns (uint256)
    {
        return tokenToWant(weth, _amtInWei);
    }

    function getTokenOutPathVelo(address _token_in, address _token_out)
        internal
        view
        returns (IVelodromeRouter.route[] memory _path)
    {
        address _weth = address(weth);
        address _usdc = address(usdc);
        bool is_weth = _token_in == _weth || _token_out == _weth;
        bool is_usdc = _token_in == _usdc || _token_out == _usdc;
        _path = new IVelodromeRouter.route[](is_weth || is_usdc ? 1 : 2);

        if (is_weth || is_usdc) {
            _path[0] = IVelodromeRouter.route(_token_in, _token_out, false);
        } else {
            bool _veloUseUsdcIntermediate = veloUseUsdcIntermediate;
            address intermediate = _veloUseUsdcIntermediate ? _usdc : _weth;
            _path[0] = IVelodromeRouter.route(_token_in, intermediate, false);
            _path[1] = IVelodromeRouter.route(
                intermediate,
                _token_out,
                _veloUseUsdcIntermediate && veloWantIsStable
            );
        }
    }

    function _sellTokenForWant(
        address token,
        uint256 amountIn,
        uint256 minOut
    ) internal {
        if (amountIn == 0) {
            return;
        }
        VELODROME_ROUTER.swapExactTokensForTokens(
            amountIn,
            minOut,
            getTokenOutPathVelo(token, address(want)),
            address(this),
            block.timestamp
        );
    }

    // Section: Interactions with Aave Protocol

    function getProtocolCollatRatios()
        internal
        view
        returns (uint256 ltv, uint256 liquidationThreshold)
    {
        uint8 _emodeCategory = uint8(POOL.getUserEMode(address(this)));

        if (_emodeCategory == 0) {
            // emode disabled
            (, ltv, liquidationThreshold, , , , , , , ) = protocolDataProvider
                .getReserveConfigurationData(address(want));
        } else {
            DataTypes.EModeCategory memory _eModeCategoryData =
                POOL.getEModeCategoryData(_emodeCategory);
            ltv = uint256(_eModeCategoryData.ltv);
            liquidationThreshold = uint256(
                _eModeCategoryData.liquidationThreshold
            );
        }
        // convert bps to wad
        ltv = ltv * WAD_BPS_RATIO;
        liquidationThreshold = liquidationThreshold * WAD_BPS_RATIO;
    }

    function getAssets() internal view returns (address[] memory assets) {
        assets = new address[](2);
        assets[0] = address(aToken);
        assets[1] = address(debtToken);
    }

    function _updateRewardTokens() internal {
        IRewardsController _rewardsController = rewardsController;
        rewardTokens = _rewardsController.getRewardsByAsset(address(aToken));
        uint256 rewardTokenCount = rewardTokens.length;

        address[] memory debtTokenRewards =
            _rewardsController.getRewardsByAsset(address(debtToken));
        for (uint256 i = 0; i < debtTokenRewards.length; i++) {
            bool seen = false;
            for (uint256 j = 0; j < rewardTokenCount; j++) {
                if (debtTokenRewards[i] == rewardTokens[j]) {
                    seen = true;
                    break;
                }
            }
            if (!seen) {
                rewardTokens.push(debtTokenRewards[i]);
            }
        }
    }

    function _autoConfigureLTVs() internal {
        (uint256 ltv, uint256 liquidationThreshold) = getProtocolCollatRatios();
        targetCollatRatio = ltv - DEFAULT_COLLAT_TARGET_MARGIN;
        maxCollatRatio = liquidationThreshold - DEFAULT_COLLAT_MAX_MARGIN;
        maxBorrowCollatRatio = ltv - DEFAULT_COLLAT_MAX_MARGIN;
    }

    // Section: LTV Math

    function getBorrowFromDeposit(uint256 deposit, uint256 collatRatio)
        internal
        pure
        returns (uint256)
    {
        return (deposit * collatRatio) / COLLATERAL_RATIO_PRECISION;
    }

    function getDepositFromBorrow(uint256 borrow, uint256 collatRatio)
        internal
        pure
        returns (uint256)
    {
        return (borrow * COLLATERAL_RATIO_PRECISION) / collatRatio;
    }

    function getBorrowFromSupply(uint256 supply, uint256 collatRatio)
        internal
        pure
        returns (uint256)
    {
        return
            (supply * collatRatio) / (COLLATERAL_RATIO_PRECISION - collatRatio);
    }

    // Section: Misc Utils

    function approveRouterRewardSpend() internal {
        for (uint256 i = 0; i < rewardTokens.length; i++) {
            approveMaxSpend(rewardTokens[i], address(VELODROME_ROUTER));
        }
    }

    function approveMaxSpend(address token, address spender) internal {
        IERC20(token).safeApprove(spender, type(uint256).max);
    }
}
