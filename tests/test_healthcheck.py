from utils import actions
import brownie
from brownie import Contract, ZERO_ADDRESS


def test_healthcheck(
    user, vault, token, amount, strategy, chain, strategist, gov, enable_healthcheck
):
    assert enable_healthcheck == True
    # Deposit to the vault
    actions.user_deposit(user, vault, token, amount)

    assert strategy.doHealthCheck()
    assert strategy.healthCheck() != ZERO_ADDRESS

    chain.sleep(1)
    strategy.harvest({"from": strategist})

    chain.sleep(24 * 3600)
    chain.mine(1)

    strategy.setDoHealthCheck(True, {"from": gov})

    loss_amount = amount * 0.05
    actions.generate_loss(strategy, loss_amount)

    # Harvest should revert because the loss in unacceptable
    # The revert crashes ganache, so this check is commented out
    # with brownie.reverts("!healthcheck"):
    #     strategy.harvest({"from": strategist})

    # we disable the healthcheck
    strategy.setDoHealthCheck(False, {"from": gov})

    # the harvest should go through, taking the loss
    tx = strategy.harvest({"from": strategist})
    assert tx.events["Harvested"]["loss"] <= loss_amount
