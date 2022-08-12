from utils import utils, actions
import pytest
from brownie import reverts, Contract, ZERO_ADDRESS
from weiroll import WeirollPlanner, WeirollContract


def test_yswaps(
    chain,
    token,
    vault,
    strategy,
    user,
    strategist,
    management,
    gov,
    amount,
    weth,
    usdc,
    RELATIVE_APPROX,
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
    assert (
        pytest.approx(strategy.getCurrentCollatRatio(), rel=RELATIVE_APPROX)
        == strategy.targetCollatRatio()
    )

    strategy.tend({"from": strategist})

    utils.strategy_status(vault, strategy)

    utils.sleep(3 * 24 * 3600)
    utils.strategy_status(vault, strategy)
    assert strategy.estimatedRewardsInWant() > 0

    trade_factory = Contract("0x21d7B09Bcf08F7b6b872BED56cB32416AE70bCC8")

    with reverts():
        strategy.updateTradeFactoryPermissions(trade_factory, {"from": management})

    assert strategy.tradeFactory() == ZERO_ADDRESS
    strategy.updateTradeFactoryPermissions(trade_factory, {"from": gov})
    assert strategy.tradeFactory() == trade_factory

    strategy.manualClaimRewards({"from": management})

    reward_tokens = [
        Contract(reward_token) for reward_token in strategy.getRewardTokens()
    ]
    router = WeirollContract.createContract(Contract(strategy.router()))
    receiver = strategy
    token_out = token

    planner = WeirollPlanner(trade_factory)

    token_bal_before = token.balanceOf(strategy)

    for reward_token in reward_tokens:
        print(reward_token.symbol())
        token_in = WeirollContract.createContract(reward_token)

        amount_in = reward_token.balanceOf(strategy)
        print(
            f"Executing trade {id}, tokenIn: {reward_token.symbol()} -> tokenOut {token.symbol()} w/ amount in {amount_in/1e18}"
        )

        route = []
        if token.symbol() == "WETH" or token.symbol() == "USDC":
            route = [(token_in.address, token.address, False)]
        elif token.symbol() == "DAI":
            route = [
                (token_in.address, usdc.address, False),
                (usdc.address, token.address, True),
            ]
        else:
            pytest.skip("Unknown path")

        planner.add(
            token_in.transferFrom(
                strategy.address,
                trade_factory.address,
                amount_in,
            )
        )

        planner.add(
            token_in.approve(
                router.address,
                amount_in,
            )
        )

        planner.add(
            router.swapExactTokensForTokens(
                amount_in,
                0,
                route,
                receiver.address,
                2**256 - 1,
            )
        )

    cmds, state = planner.plan()
    trade_factory.execute(cmds, state, {"from": trade_factory.governance()})

    token_bal_after = token.balanceOf(strategy)
    assert token_bal_after > token_bal_before

    tx = strategy.harvest({"from": strategist})
    assert tx.events["Harvested"]["profit"] > 0
    utils.strategy_status(vault, strategy)

    strategy.removeTradeFactoryPermissions({"from": management})
    assert strategy.tradeFactory() == ZERO_ADDRESS

    # withdrawal
    vault.withdraw({"from": user})
    assert (
        pytest.approx(token.balanceOf(user), rel=RELATIVE_APPROX) == user_balance_before
        or token.balanceOf(user) > user_balance_before
    )
