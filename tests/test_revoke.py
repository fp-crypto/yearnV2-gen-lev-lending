import pytest
from utils import actions, checks, utils


def test_revoke_strategy_from_vault(
    chain, token, vault, strategy, strategist, amount, user, gov, RELATIVE_APPROX
):
    # Deposit to the vault and harvest
    actions.user_deposit(user, vault, token, amount)
    chain.sleep(1)
    strategy.harvest({"from": strategist})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    tx = vault.revokeStrategy(strategy.address, {"from": gov})
    utils.rest(tx)
    tx = strategy.harvest({"from": strategist})
    utils.rest(tx)
    assert pytest.approx(token.balanceOf(vault.address), rel=RELATIVE_APPROX) == amount


def test_revoke_strategy_from_strategy(
    chain, token, vault, strategy, strategist, amount, gov, user, RELATIVE_APPROX
):
    # Deposit to the vault and harvest
    actions.user_deposit(user, vault, token, amount)
    chain.sleep(1)
    strategy.harvest({"from": strategist})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    tx = strategy.setEmergencyExit({"from": gov})
    utils.rest(tx)
    tx = strategy.harvest({"from": strategist})
    utils.rest(tx)
    assert pytest.approx(token.balanceOf(vault.address), rel=RELATIVE_APPROX) == amount


def test_revoke_with_profit(
    chain, token, token_whale, vault, strategy, strategist, amount, user, gov, RELATIVE_APPROX
):
    actions.user_deposit(user, vault, token, amount)
    chain.sleep(1)
    strategy.harvest({"from": strategist})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    profit_amount = amount * 0.05  # generating a 5% profit
    actions.generate_profit(strategy, token_whale, profit_amount)

    # Revoke strategy
    tx = vault.revokeStrategy(strategy.address, {"from": gov})
    utils.rest(tx)
    tx = strategy.harvest({"from": strategist})
    utils.rest(tx)
    checks.check_revoked_strategy(vault, strategy)
