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
    yield accounts[6]


@pytest.fixture(scope="session")
def strat_ms(accounts):
    yield accounts[7]


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
    "DAI": "0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1",
    "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
    "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
    "USDC": "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8",
    "WBTC": "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f",
}

# TODO: uncomment those tokens you want to test as want
@pytest.fixture(
    params=[
        "DAI",
        #"USDT",
        #"WETH",
        #"USDC",
        #"WBTC",
    ],
    scope="session",
    autouse=True,
)
def token(request):
    yield Contract(token_addresses[request.param])


whale_addresses = {
    "DAI": "0xc5ed2333f8a2C351fCA35E5EBAdb2A82F5d254C3",
    "USDT": "0x62383739D68Dd0F844103Db8dFb05a7EdED5BBE6",
    "WETH": "0x9E722E233646E1eDEa4A913489A75262A181C911",
    "USDC": "0xBA479d5585EcEC47eDc2a571dA430A40f43c3851",
    "WBTC": "0x078f358208685046a11C85e8ad32895DED33A249",
}


@pytest.fixture(scope="session", autouse=True)
def token_whale(token):
    yield whale_addresses[token.symbol()]


token_prices = {
    "WBTC": 40_000,
    "WETH": 3_500,
    "DAI": 1,
    "USDC": 1,
    "USDT": 1,
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
    token.transfer(user, amount, {"from": token_whale})
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
    token.transfer(user, amount, {"from": token_whale})
    yield token.balanceOf(user)


@pytest.fixture
def weth():
    token_address = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
    yield Contract(token_address)


@pytest.fixture
def weth_amount(user, weth):
    weth_amount = 10 ** weth.decimals()
    weth.transfer(
        user, weth_amount, {"from": "0x9E722E233646E1eDEa4A913489A75262A181C911"} # WETH WHALE
    )
    yield weth_amount


@pytest.fixture(scope="function", autouse=True)
def vault(pm, gov, rewards, guardian, management, token):
    Vault = pm(config["dependencies"][0]).Vault
    #vault = guardian.deploy(Vault)
    vault = Vault.deploy({"from":guardian})
    vault.initialize(token, gov, rewards, "", "", guardian, management)
    vault.setDepositLimit(2 ** 256 - 1, {"from": gov})
    vault.setManagement(management, {"from": gov})
    vault.setManagementFee(0, {"from": gov})
    yield vault


@pytest.fixture(scope="function")
def factory(strategist, vault, LevRadiantFactory):
    yield strategist.deploy(LevRadiantFactory, vault)


@pytest.fixture(scope="function")
def strategy(chain, keeper, vault, factory, gov, strategist, Strategy):
    strategy = Strategy.at(factory.original())
    strategy.setKeeper(keeper, {"from": strategist})
    vault.addStrategy(strategy, 10_000, 0, 2 ** 256 - 1, 1_000, {"from": gov})
    chain.sleep(1)
    chain.mine()
    yield strategy


@pytest.fixture()
def enable_healthcheck(strategy, gov):
    strategy.setHealthCheck("0x32059ccE723b4DD15dD5cb2a5187f814e6c470bC", {"from": gov}) ## ARB HEALTHCHECK
    strategy.setDoHealthCheck(True, {"from": gov})
    yield True


@pytest.fixture(scope="session", autouse=True)
def RELATIVE_APPROX():
    yield 1e-5
