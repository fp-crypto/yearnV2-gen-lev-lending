import pytest
from utils import actions, utils
from brownie import reverts


def test_migration(
    token,
    vault,
    strategy,
    amount,
    Strategy,
    strategist,
    gov,
    user,
    RELATIVE_APPROX,
):
    # Deposit to the vault and harvest
    actions.user_deposit(user, vault, token, amount)

    utils.sleep(1)
    strategy.harvest({"from": gov})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    pre_want_balance = token.balanceOf(strategy)

    new_strategy = strategist.deploy(Strategy, vault)

    # mirgration with more than dust reverts, there is no way to transfer the debt position
    with reverts():
        vault.migrateStrategy(strategy, new_strategy, {"from": gov})

    vault.revokeStrategy(strategy, {"from": gov})
    strategy.harvest({"from": gov})
    utils.sleep(1)

    vault.migrateStrategy(strategy, new_strategy, {"from": gov})
    utils.sleep(1)
    vault.updateStrategyDebtRatio(new_strategy, 10_000, {"from": gov})
    new_strategy.harvest({"from": gov})
    utils.sleep(1)

    assert (
        pytest.approx(new_strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX)
        == amount
    )

    assert pytest.approx(pre_want_balance, rel=RELATIVE_APPROX) == token.balanceOf(
        new_strategy
    )

    # check that harvest work as expected
    new_strategy.harvest({"from": gov})
