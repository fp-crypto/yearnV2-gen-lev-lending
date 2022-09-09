import pytest
from brownie import config, Contract, network
import requests

# Function scoped isolation fixture to enable xdist.
# Snapshots the chain before each test and reverts after test completion.
@pytest.fixture(scope="function", autouse=True)
def shared_setup(fn_isolation):
    pass


@pytest.fixture(scope="session")
def gov(accounts):
    yield accounts.at("0xC0E2830724C946a6748dDFE09753613cd38f6767", force=True)


@pytest.fixture(scope="session")
def strat_ms(accounts):
    yield accounts.at("0x72a34AbafAB09b15E7191822A679f28E067C4a16", force=True)


@pytest.fixture(scope="session")
def user(accounts):
    yield accounts[0]


@pytest.fixture(scope="session")
def rewards(accounts):
    yield accounts[1]


@pytest.fixture(scope="session")
def guardian(accounts):
    yield accounts[2]


@pytest.fixture(scope="session")
def management(strat_ms):
    yield strat_ms  # accounts[3]


@pytest.fixture(scope="session")
def strategist(accounts):
    yield accounts[4]


@pytest.fixture(scope="session")
def keeper(accounts):
    yield accounts[5]


token_addresses = {
    "DAI": "0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1",  # WBTC
    # "ETH": "0x74b23882a30290451A17c44f4F05243b6b58C76d",  # WETH
    # "DAI": "0x8D11eC38a3EB5E956B052f67Da8Bdc9bef8Abf3E",  # DAI
    # "USDC": "0x04068DA6C83AFCFA0e13ba15A6696662335D5B75",  # USDC
    # "WFTM": "0x21be370D5312f44cB42ce377BC9b8a0cEF1A4C83",  # WFTM
    # "MIM": "0x82f0B8B456c1A451378467398982d4834b6829c1",  # MIM
}

# TODO: uncomment those tokens you want to test as want
@pytest.fixture(
    params=[
        # "BTC",   # WBTC
        # "ETH",   # ETH
        # "DAI",   # DAI
        # "USDC",  # USDC
        "DAI",  # WFTM
        # "MIM",   # MIM
    ],
    scope="session",
    autouse=True,
)
def token(request):
    yield Contract(token_addresses[request.param])


whale_addresses = {
    "DAI": "0xBA479d5585EcEC47eDc2a571dA430A40f43c3851",
    # "ETH": "0xC772BA6C2c28859B7a0542FAa162a56115dDCE25",
    # "DAI": "0x8CFA87aD11e69E071c40D58d2d1a01F862aE01a8",
    # "USDC": "0x2dd7C9371965472E5A5fD28fbE165007c61439E1",
    # "WFTM": "0x5AA53f03197E08C4851CAD8C92c7922DA5857E5d",
    # "MIM": "0x2dd7C9371965472E5A5fD28fbE165007c61439E1",
}


@pytest.fixture(scope="session", autouse=True)
def token_whale(token):
    yield whale_addresses[token.symbol()]


token_prices = {
    "BTC": 40_000,
    "ETH": 3_500,
    "YFI": 30_000,
    "DAI": 1,
    "USDC": 1,
    "WFTM": 2,
    "MIM": 1,
}


@pytest.fixture(autouse=True, scope="function")
def amount(token, token_whale, user):
    # this will get the number of tokens (around $1m worth of token)
    base_amount = round(1_000_000 / token_prices[token.symbol()])
    amount = base_amount * 10 ** token.decimals()
    # In order to get some funds for the token you are about to use,
    # it impersonate a whale address
    if amount > token.balanceOf(token_whale):
        amount = token.balanceOf(token_whale)
    token.transfer(user, amount, {"from": token_whale, "allow_revert": True, "gas_limit":20000000, "max_fee":200000000000, "priority_fee":10000000000})
    yield amount


@pytest.fixture(scope="function")
def big_amount(token, token_whale, user):
    # this will get the number of tokens (around $9m worth of token)
    ten_minus_one_million = round(9_000_000 / token_prices[token.symbol()])
    amount = ten_minus_one_million * 10 ** token.decimals()
    # In order to get some funds for the token you are about to use,
    # it impersonate a whale address
    if amount > token.balanceOf(token_whale):
        amount = token.balanceOf(token_whale)
    token.transfer(user, amount, {"from": token_whale, "allow_revert": True, "gas_limit":20000000, "max_fee":200000000000, "priority_fee":10000000000})
    yield token.balanceOf(user)


# @pytest.fixture
# def wftm():
#     yield Contract("0x21be370D5312f44cB42ce377BC9b8a0cEF1A4C83")


@pytest.fixture
def weth():
    token_address = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
    yield Contract(token_address)


@pytest.fixture
def weth_amount(user, weth):
    weth_amount = 10 ** weth.decimals()
    weth.transfer(
        user, weth_amount, {"from": "0xC948eB5205bDE3e18CAc4969d6ad3a56ba7B2347", "allow_revert": True, "gas_limit":20000000, "max_fee":200000000000, "priority_fee":10000000000} # WETH WHALE
    )
    yield weth_amount


@pytest.fixture(scope="function", autouse=True)
def vault(pm, gov, rewards, guardian, management, token):
    Vault = pm(config["dependencies"][0]).Vault
    #vault = guardian.deploy(Vault)
    vault = Vault.deploy({"from":guardian, "allow_revert": True, "gas_limit":20000000, "max_fee":200000000000, "priority_fee":10000000000})
    vault.initialize(token, gov, rewards, "", "", guardian, management)
    vault.setDepositLimit(2 ** 256 - 1, {"from": gov, "allow_revert": True, "gas_limit":20000000, "max_fee":200000000000, "priority_fee":10000000000})
    vault.setManagement(management, {"from": gov, "allow_revert": True, "gas_limit":20000000, "max_fee":200000000000, "priority_fee":10000000000})
    vault.setManagementFee(0, {"from": gov, "allow_revert": True, "gas_limit":20000000, "max_fee":200000000000, "priority_fee":10000000000})
    yield vault


@pytest.fixture(scope="function")
def factory(strategist, vault, LevGeistFactory):
    yield strategist.deploy(LevGeistFactory, vault)


@pytest.fixture(scope="function")
def strategy(chain, keeper, vault, factory, gov, strategist, Strategy):
    strategy = Strategy.at(factory.original())
    strategy.setKeeper(keeper, {"from": strategist, "allow_revert": True, "gas_limit":20000000, "max_fee":200000000000, "priority_fee":10000000000})
    vault.addStrategy(strategy, 10_000, 0, 2 ** 256 - 1, 1_000, {"from": gov, "allow_revert": True, "gas_limit":20000000, "max_fee":200000000000, "priority_fee":10000000000})
    chain.sleep(1)
    chain.mine()
    yield strategy


@pytest.fixture()
def enable_healthcheck(strategy, gov):
    strategy.setHealthCheck("0xf13Cd6887C62B5beC145e30c38c4938c5E627fe0", {"from": gov})
    strategy.setDoHealthCheck(True, {"from": gov, "allow_revert": True, "gas_limit":20000000, "max_fee":200000000000, "priority_fee":10000000000})
    yield True


@pytest.fixture(scope="session", autouse=True)
def RELATIVE_APPROX():
    yield 1e-5
