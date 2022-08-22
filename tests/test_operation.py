from brownie import Contract, reverts
import pytest
from utils import actions, utils


@pytest.fixture(
    params=[
        True,
        False,
    ],
    scope="function",
    autouse=True,
)
def flashloan_enabled(request, strategy, gov):
    enable = request.param
    strategy.setFlashloanEnabled(enable, {"from": gov})
    assert strategy.flashloanEnabled() == enable
    yield enable


def test_basic_operation(
    chain, token, vault, strategy, user, strategist, amount, RELATIVE_APPROX
):
    # Deposit to the vault
    user_balance_before = token.balanceOf(user)
    actions.user_deposit(user, vault, token, amount)

    # harvest
    chain.sleep(1)
    strategy.harvest({"from": strategist})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    utils.strategy_status(vault, strategy)

    assert token.balanceOf(strategy) <= strategy.minWant()
    strategy.tend({"from": strategist})

    assert (
        pytest.approx(strategy.getCurrentCollatRatio(), abs=strategy.minRatio())
        == strategy.targetCollatRatio()
    )

    utils.strategy_status(vault, strategy)

    utils.sleep(3 * 24 * 3600)
    utils.strategy_status(vault, strategy)
    assert strategy.estimatedRewardsInWant() > 0

    strategy.harvest({"from": strategist})

    # withdrawal
    vault.withdraw({"from": user})
    assert (
        pytest.approx(token.balanceOf(user), rel=RELATIVE_APPROX) == user_balance_before
        or token.balanceOf(user) > user_balance_before
    )


def test_withdraw(
    token,
    vault,
    strategy,
    user,
    strategist,
    amount,
    RELATIVE_APPROX,
):
    # Deposit to the vault
    user_balance_before = token.balanceOf(user)
    actions.user_deposit(user, vault, token, amount)

    # harvest
    utils.sleep(1)
    strategy.harvest({"from": strategist})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    utils.sleep(1 * 24 * 3600)

    utils.strategy_status(vault, strategy)
    strategy.harvest({"from": strategist})
    utils.sleep()

    # withdrawal
    for i in range(1, 10):
        print(i)
        utils.sleep(1)
        utils.strategy_status(vault, strategy)
        vault.withdraw(int(amount / 10), user, 10_000, {"from": user})
        assert token.balanceOf(user) >= user_balance_before * i / 10

    utils.sleep(1)
    strategy.harvest({"from": strategist})
    utils.sleep()
    vault.withdraw({"from": user})
    assert token.balanceOf(user) > user_balance_before
    utils.strategy_status(vault, strategy)


@pytest.mark.parametrize("percent_max_leverage", [1e-5, 0.1, 0.25, 0.5, 0.75, 1])
def test_apr(
    chain,
    gov,
    token,
    vault,
    strategy,
    user,
    strategist,
    amount,
    percent_max_leverage,
    pool,
    flashloan_enabled,
    RELATIVE_APPROX,
):
    strategy.setCollateralTargets(
        strategy.maxBorrowCollatRatio() * percent_max_leverage,
        strategy.maxCollatRatio(),
        strategy.maxBorrowCollatRatio(),
        {"from": gov},
    )
    # Deposit to the vault
    actions.user_deposit(user, vault, token, amount)

    # harvest
    chain.sleep(1)
    strategy.harvest({"from": strategist})
    if (
        percent_max_leverage == 1
        and not pool.getUserEMode(strategy) == 0
        and not flashloan_enabled
    ):  # extra tend when using very high leverage
        strategy.tend({"from": strategist})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    utils.sleep(7 * 24 * 3600)

    vault.revokeStrategy(strategy.address, {"from": gov})
    ltv = strategy.getCurrentCollatRatio() / 1e18
    strategy.harvest({"from": strategist})
    print(
        f"APR @ {ltv:.2%} LTV: {(token.balanceOf(vault)-amount)*52*100/amount:.2f}% on {amount/10**token.decimals():,.2f} {token.symbol()}"
    )


def test_harvest_after_long_idle_period(
    chain, token, vault, strategy, user, strategist, amount, RELATIVE_APPROX
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
    chain, token, vault, strategy, user, strategist, amount, RELATIVE_APPROX
):
    # Deposit to the vault
    actions.user_deposit(user, vault, token, amount)
    chain.sleep(1)
    strategy.harvest({"from": strategist})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    # set emergency and exit
    strategy.setEmergencyExit({"from": strategist})
    chain.sleep(1)
    strategy.harvest({"from": strategist})
    assert strategy.estimatedTotalAssets() < amount


def test_harvest_with_credit(
    token,
    vault,
    strategy,
    user,
    strategist,
    amount,
    RELATIVE_APPROX,
):
    # Deposit to the vault
    user_balance_before = token.balanceOf(user)
    half_amount = amount / 2
    actions.user_deposit(user, vault, token, half_amount)

    # harvest
    utils.sleep(1)
    strategy.harvest({"from": strategist})
    assert (
        pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX)
        == half_amount
    )

    utils.sleep(1 * 24 * 3600)

    actions.user_deposit(user, vault, token, token.balanceOf(user))
    assert vault.creditAvailable(strategy) > 0

    utils.strategy_status(vault, strategy)
    strategy.harvest({"from": strategist})
    assert token.balanceOf(strategy) <= strategy.minWant()
    utils.sleep()

    vault.withdraw({"from": user})
    assert token.balanceOf(user) > user_balance_before
    utils.strategy_status(vault, strategy)


@pytest.mark.parametrize(
    "starting_debt_ratio", [100, 500, 1_000, 2_500, 5_000, 7_500, 9_500, 9_900]
)
def test_increase_debt_ratio(
    chain,
    gov,
    token,
    vault,
    strategy,
    user,
    strategist,
    amount,
    starting_debt_ratio,
    pool,
    flashloan_enabled,
    RELATIVE_APPROX,
):
    # Deposit to the vault and harvest
    actions.user_deposit(user, vault, token, amount)
    vault.updateStrategyDebtRatio(strategy.address, starting_debt_ratio, {"from": gov})
    chain.sleep(1)
    strategy.harvest({"from": strategist})
    part_amount = int(amount * starting_debt_ratio / 10_000)

    if (
        not pool.getUserEMode(strategy) == 0 and not flashloan_enabled
    ):  # extra tend when using very high leverage
        strategy.tend({"from": strategist})

    utils.strategy_status(vault, strategy)

    assert (
        pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX)
        == part_amount
    )
    assert token.balanceOf(strategy) <= strategy.minWant()
    assert (
        pytest.approx(strategy.getCurrentCollatRatio(), abs=strategy.minRatio())
        == strategy.targetCollatRatio()
    )

    vault.updateStrategyDebtRatio(strategy.address, 10_000, {"from": gov})
    chain.sleep(1)
    strategy.harvest({"from": strategist})

    if (
        not pool.getUserEMode(strategy) == 0 and not flashloan_enabled
    ):  # extra tend when using very high leverage
        strategy.tend({"from": strategist})

    utils.strategy_status(vault, strategy)

    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount
    assert token.balanceOf(strategy) <= strategy.minWant()
    assert (
        pytest.approx(strategy.getCurrentCollatRatio(), abs=strategy.minRatio())
        == strategy.targetCollatRatio()
    )


@pytest.mark.parametrize(
    "ending_debt_ratio", [100, 500, 1_000, 2_500, 5_000, 7_500, 9_500, 9_900]
)
def test_decrease_debt_ratio(
    gov,
    token,
    vault,
    strategy,
    user,
    strategist,
    amount,
    ending_debt_ratio,
    pool,
    flashloan_enabled,
    RELATIVE_APPROX,
):
    # Deposit to the vault and harvest
    actions.user_deposit(user, vault, token, amount)
    vault.updateStrategyDebtRatio(strategy.address, 10_000, {"from": gov})
    utils.sleep(1)
    strategy.harvest({"from": strategist})

    if (
        not pool.getUserEMode(strategy) == 0 and not flashloan_enabled
    ):  # extra tend when using very high leverage
        strategy.tend({"from": strategist})

    utils.strategy_status(vault, strategy)

    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount
    assert token.balanceOf(strategy) <= strategy.minWant()
    assert (
        pytest.approx(strategy.getCurrentCollatRatio(), abs=strategy.minRatio())
        == strategy.targetCollatRatio()
    )

    vault.updateStrategyDebtRatio(strategy.address, ending_debt_ratio, {"from": gov})
    utils.sleep(1)
    strategy.harvest({"from": strategist})

    if (
        not pool.getUserEMode(strategy) == 0 and not flashloan_enabled
    ):  # extra tend when using very high leverage
        strategy.tend({"from": strategist})

    utils.strategy_status(vault, strategy)

    part_amount = int(amount * ending_debt_ratio / 10_000)
    assert (
        pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX)
        == part_amount
    )
    assert token.balanceOf(strategy) <= strategy.minWant()
    assert (
        pytest.approx(strategy.getCurrentCollatRatio(), abs=strategy.minRatio())
        == strategy.targetCollatRatio()
    )


def test_large_deleverage(
    gov, token, vault, strategy, user, strategist, amount, RELATIVE_APPROX
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


def test_larger_deleverage(
    gov, token, vault, strategy, user, strategist, big_amount, RELATIVE_APPROX
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
    with reverts("!want"):
        strategy.sweep(token, {"from": gov})

    # Vault share token doesn't work
    with reverts("!shares"):
        strategy.sweep(vault.address, {"from": gov})

    if token.address == weth.address:
        return
    before_balance = weth.balanceOf(gov)
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
    strategy.harvest({"from": strategist})

    strategy.harvestTrigger(0)
    strategy.tendTrigger(0)


def test_tend(
    chain,
    protocol_data_provider,
    vault,
    strategy,
    token,
    amount,
    user,
    strategist,
    pool,
    RELATIVE_APPROX,
):
    # Deposit to the vault and harvest
    actions.user_deposit(user, vault, token, amount)
    chain.sleep(1)
    strategy.harvest({"from": strategist})

    if pool.getUserEMode(strategy) == 0:
        liquidationThreshold = protocol_data_provider.getReserveConfigurationData(
            token
        ).dict()["liquidationThreshold"]
    else:
        liquidationThreshold = pool.getEModeCategoryData(
            pool.getUserEMode(strategy)
        ).dict()["liquidationThreshold"]

    (deposits, borrows) = strategy.getCurrentPosition()
    theoDeposits = borrows * 1e4 / (liquidationThreshold - 90)
    toLose = int(deposits - theoDeposits)

    utils.strategy_status(vault, strategy)
    actions.generate_loss(strategy, toLose)
    utils.strategy_status(vault, strategy)

    strategy.setDebtThreshold(
        toLose * 1.1, {"from": strategist}
    )  # prevent harvestTrigger

    assert strategy.tendTrigger(0)

    strategy.tend({"from": strategist})

    utils.strategy_status(vault, strategy)

    assert not strategy.tendTrigger(0)
    assert (
        pytest.approx(strategy.getCurrentCollatRatio(), rel=RELATIVE_APPROX)
        == strategy.targetCollatRatio()
    )
