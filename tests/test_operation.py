import brownie
from brownie import Contract
import pytest
from utils import actions, checks, utils


def test_operation(
    chain, accounts, token, vault, strategy, user, strategist, amount, RELATIVE_APPROX
):
    # Deposit to the vault
    user_balance_before = token.balanceOf(user)
    actions.user_deposit(user, vault, token, amount)

    # harvest
    chain.sleep(1)
    strategy.harvest({"from": strategist})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    utils.strategy_status(vault, strategy)

    # tend()
    strategy.tend({"from": strategist})

    utils.sleep(3 * 24 * 3600)
    strategy.harvest({"from": strategist})

    # withdrawal
    vault.withdraw({"from": user})
    assert (
        pytest.approx(token.balanceOf(user), rel=RELATIVE_APPROX) == user_balance_before
    )


@pytest.mark.skip()
def test_big_operation(
    chain,
    accounts,
    token,
    vault,
    strategy,
    user,
    strategist,
    big_amount,
    RELATIVE_APPROX,
):
    # Deposit to the vault
    user_balance_before = token.balanceOf(user)
    actions.user_deposit(user, vault, token, big_amount)

    # harvest
    chain.sleep(1)
    strategy.harvest({"from": strategist})
    assert (
        pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX)
        == big_amount
    )

    utils.strategy_status(vault, strategy)

    utils.sleep(3 * 24 * 3600)
    strategy.harvest({"from": strategist})

    utils.strategy_status(vault, strategy)

    utils.sleep(6 * 3600)

    # withdrawal
    vault.withdraw({"from": user})
    assert (
        pytest.approx(token.balanceOf(user), rel=RELATIVE_APPROX) == user_balance_before
    )


def test_apr(
    chain,
    accounts,
    gov,
    token,
    vault,
    strategy,
    user,
    strategist,
    amount,
    RELATIVE_APPROX,
):
    # Deposit to the vault
    actions.user_deposit(user, vault, token, amount)

    # harvest
    chain.sleep(1)
    strategy.harvest({"from": strategist})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    utils.strategy_status(vault, strategy)

    utils.sleep(7 * 24 * 3600)
    utils.strategy_status(vault, strategy)

    vault.revokeStrategy(strategy.address, {"from": gov})
    strategy.harvest({"from": strategist})

    utils.strategy_status(vault, strategy)
    print(f"APR: {(token.balanceOf(vault)-amount)*52*100/amount:.2f}%")


def test_harvest_after_long_idle_period(
    chain, accounts, token, vault, strategy, user, strategist, amount, RELATIVE_APPROX
):
    # Deposit to the vault
    actions.user_deposit(user, vault, token, amount)

    # harvest
    chain.sleep(1)
    strategy.harvest({"from": strategist})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    utils.strategy_status(vault, strategy)

    utils.sleep(26 * 7 * 24 * 3600)
    utils.strategy_status(vault, strategy)

    strategy.harvest({"from": strategist})

    utils.strategy_status(vault, strategy)


def test_emergency_exit(
    chain, accounts, token, vault, strategy, user, strategist, amount, RELATIVE_APPROX
):
    # Deposit to the vault
    actions.user_deposit(user, vault, token, amount)
    chain.sleep(1)
    strategy.harvest({"from": strategist})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    # set emergency and exit
    strategy.setEmergencyExit()
    chain.sleep(1)
    strategy.harvest({"from": strategist})
    assert strategy.estimatedTotalAssets() < amount


def test_increase_debt_ratio(
    chain, gov, token, vault, strategy, user, strategist, amount, RELATIVE_APPROX
):
    # Deposit to the vault and harvest
    actions.user_deposit(user, vault, token, amount)
    vault.updateStrategyDebtRatio(strategy.address, 5_000, {"from": gov})
    chain.sleep(1)
    strategy.harvest({"from": strategist})
    half = int(amount / 2)

    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == half

    vault.updateStrategyDebtRatio(strategy.address, 10_000, {"from": gov})
    chain.sleep(1)
    strategy.harvest({"from": strategist})

    utils.strategy_status(vault, strategy)

    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount


def test_decrease_debt_ratio(
    chain, gov, token, vault, strategy, user, strategist, amount, RELATIVE_APPROX
):
    # Deposit to the vault and harvest
    actions.user_deposit(user, vault, token, amount)
    vault.updateStrategyDebtRatio(strategy.address, 10_000, {"from": gov})
    utils.sleep(1)
    strategy.harvest({"from": strategist})

    utils.strategy_status(vault, strategy)

    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    # Two harvests needed to unlock
    vault.updateStrategyDebtRatio(strategy.address, 5_000, {"from": gov})
    utils.sleep(1)
    strategy.harvest({"from": strategist})

    utils.strategy_status(vault, strategy)

    half = int(amount / 2)
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == half


def test_large_deleverage(
    chain, gov, token, vault, strategy, user, strategist, amount, RELATIVE_APPROX
):
    # Deposit to the vault and harvest
    actions.user_deposit(user, vault, token, amount)
    vault.updateStrategyDebtRatio(strategy.address, 10_000, {"from": gov})
    utils.sleep(1)
    strategy.harvest({"from": strategist})

    utils.strategy_status(vault, strategy)

    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    # Two harvests needed to unlock
    vault.updateStrategyDebtRatio(strategy.address, 1_000, {"from": gov})
    utils.sleep(1)
    strategy.harvest({"from": strategist})

    utils.strategy_status(vault, strategy)

    tenth = int(amount / 10)
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == tenth


@pytest.mark.skip()
def test_larger_deleverage(
    chain, gov, token, vault, strategy, user, strategist, big_amount, RELATIVE_APPROX
):
    # Deposit to the vault and harvest
    actions.user_deposit(user, vault, token, big_amount)
    vault.updateStrategyDebtRatio(strategy.address, 10_000, {"from": gov})
    utils.sleep(1)
    strategy.harvest({"from": strategist})

    utils.strategy_status(vault, strategy)

    assert (
        pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX)
        == big_amount
    )

    vault.updateStrategyDebtRatio(strategy.address, 1_000, {"from": gov})
    n = 0
    while vault.debtOutstanding(strategy) > 0 and n < 5:
        utils.sleep(1)
        strategy.harvest({"from": strategist})
        utils.strategy_status(vault, strategy)
        n += 1

    tenth = int(big_amount / 10)
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == tenth


def test_sweep(gov, vault, strategy, token, user, amount, weth, weth_amount):
    # Strategy want token doesn't work
    token.transfer(strategy, amount, {"from": user})
    assert token.address == strategy.want()
    assert token.balanceOf(strategy) > 0
    with brownie.reverts("!want"):
        strategy.sweep(token, {"from": gov})

    # Vault share token doesn't work
    with brownie.reverts("!shares"):
        strategy.sweep(vault.address, {"from": gov})

    before_balance = weth.balanceOf(gov) + weth.balanceOf(
        strategy
    )  # strategy has some weth to pay for flashloans
    weth.transfer(strategy, weth_amount, {"from": user})
    assert weth.address != strategy.want()
    assert weth.balanceOf(user) == 0
    strategy.sweep(weth, {"from": gov})
    assert weth.balanceOf(gov) == weth_amount + before_balance


def test_triggers(chain, gov, vault, strategy, token, amount, user, strategist):
    # Deposit to the vault and harvest
    actions.user_deposit(user, vault, token, amount)
    vault.updateStrategyDebtRatio(strategy.address, 5_000, {"from": gov})
    chain.sleep(1)
    strategy.harvest()

    strategy.harvestTrigger(0)
    strategy.tendTrigger(0)


def test_tend(chain, gov, vault, strategy, token, amount, user, RELATIVE_APPROX):
    # Deposit to the vault and harvest
    actions.user_deposit(user, vault, token, amount)
    chain.sleep(1)
    strategy.harvest()

    liquidationThreshold = (
        Contract("0x057835Ad21a177dbdd3090bB1CAE03EaCF78Fc6d")  # ProtocolDataProvider
        .getReserveConfigurationData(token)
        .dict()["liquidationThreshold"]
    )

    (deposits, borrows) = strategy.getCurrentPosition()
    theoDeposits = borrows * 1e4 / (liquidationThreshold - 90)
    toLose = int(deposits - theoDeposits)

    utils.strategy_status(vault, strategy)
    actions.generate_loss(strategy, toLose)
    utils.strategy_status(vault, strategy)

    strategy.setDebtThreshold(toLose * 1.1)  # prevent harvestTrigger

    assert strategy.tendTrigger(0)

    strategy.tend()

    utils.strategy_status(vault, strategy)

    assert not strategy.tendTrigger(0)
    assert (
        pytest.approx(strategy.getCurrentCollatRatio(), rel=RELATIVE_APPROX)
        == strategy.targetCollatRatio()
    )
