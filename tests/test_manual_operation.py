from utils import actions, utils
import pytest
from brownie import reverts


def test_emode_disable(
    token,
    vault,
    strategy,
    user,
    gov,
    strategist,
    amount,
    enable_emode,
    protocol_data_provider,
    RELATIVE_APPROX,
):
    if enable_emode == 0:
        pytest.skip()  # skip test since this is a no op
    # Deposit to the vault
    user_balance_before = token.balanceOf(user)
    actions.user_deposit(user, vault, token, amount)

    # harvest
    utils.sleep(1)
    strategy.harvest({"from": strategist})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    utils.strategy_status(vault, strategy)

    utils.sleep(1)
    strategy.tend({"from": strategist})
    utils.strategy_status(vault, strategy)

    assert token.balanceOf(strategy) <= strategy.minWant()
    assert (
        pytest.approx(strategy.getCurrentCollatRatio(), abs=strategy.minRatio())
        == strategy.targetCollatRatio()
    )

    utils.sleep(1)

    with reverts():
        strategy.setEMode(False, False, {"from": gov})

    (
        _,
        ltv,
        liquidationThreshold,
        _,
        _,
        _,
        _,
        _,
        _,
        _,
    ) = protocol_data_provider.getReserveConfigurationData(token)

    ltv = ltv * 1e14
    liquidationThreshold = liquidationThreshold * 1e14

    strategy.setCollateralTargets(
        ltv - 0.02e18, liquidationThreshold - 0.005e18, ltv - 0.005e18, {"from": gov}
    )

    utils.strategy_status(vault, strategy)

    strategy.tend({"from": strategist})
    utils.strategy_status(vault, strategy)

    assert token.balanceOf(strategy) <= strategy.minWant()
    assert (
        pytest.approx(strategy.getCurrentCollatRatio(), abs=strategy.minRatio())
        == strategy.targetCollatRatio()
    )

    strategy.setEMode(False, False, {"from": gov})

    strategy.harvest({"from": strategist})
    utils.strategy_status(vault, strategy)

    # withdrawal
    vault.withdraw({"from": user})
    assert (
        pytest.approx(token.balanceOf(user), rel=RELATIVE_APPROX) == user_balance_before
        or token.balanceOf(user) > user_balance_before
    )
