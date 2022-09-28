import pytest
from utils import actions, utils
import brownie


def test_migration(
    chain,
    token,
    vault,
    strategy,
    amount,
    Strategy,
    strategist,
    gov,
    user,
    weth,
    RELATIVE_APPROX,
):
    # Deposit to the vault and harvest
    actions.user_deposit(user, vault, token, amount)

    chain.sleep(1)
    strategy.harvest({"from": gov})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    pre_want_balance = token.balanceOf(strategy)

    new_strategy = strategist.deploy(Strategy, vault)

    # mirgration with more than dust reverts, there is no way to transfer the debt position
    with brownie.reverts():
        vault.migrateStrategy(strategy, new_strategy, {"from": gov})

    tx = vault.revokeStrategy(strategy, {"from": gov})
    utils.rest(tx)
    tx = strategy.harvest({"from": gov})
    utils.rest(tx)


    vault.migrateStrategy(strategy, new_strategy, {"from": gov})
    vault.updateStrategyDebtRatio(new_strategy, 10_000, {"from": gov})
    new_strategy.harvest({"from": gov})

    assert (
        pytest.approx(new_strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX)
        == amount
    )

    assert pytest.approx(pre_want_balance, rel=RELATIVE_APPROX) == token.balanceOf(
        new_strategy
    )

    # check that harvest work as expected
    new_strategy.harvest({"from": gov})
