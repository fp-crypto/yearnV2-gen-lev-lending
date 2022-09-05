from brownie import Contract, reverts
from utils import actions, utils
import pytest


@pytest.fixture(autouse=True)
def only_test_weth(token):
    if not token.symbol() == "WETH":
        pytest.skip(f"skipping: {token.symbol()}")


def test_flashload_safety(vault, token, amount, strategy, user, strategist, gov):
    # Deposit to the vault and harvest
    actions.user_deposit(user, vault, token, amount)
    vault.updateStrategyDebtRatio(strategy.address, 10_000, {"from": gov})
    utils.sleep(1)
    strategy.harvest({"from": strategist})

    utils.strategy_status(vault, strategy)

    pool = Contract(strategy.POOL())

    with reverts():
        pool.flashLoan(
            strategy,
            [token],
            [amount],
            [2],
            strategy,
            "",
            0,
            {"from": strategist},
        )
