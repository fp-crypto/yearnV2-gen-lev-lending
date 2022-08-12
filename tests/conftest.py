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
    "WBTC": "0x68f180fcCe6836688e9084f035309E29Bf0A2095",  # WBTC
    "WETH": "0x4200000000000000000000000000000000000006",  # WETH
    "DAI": "0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1",  # DAI
    "USDC": "0x7F5c764cBc14f9669B88837ca1490cCa17c31607",  # USDC
}

# TODO: uncomment those tokens you want to test as want
@pytest.fixture(
    params=[
        # "WBTC",   # WBTC
        "WETH",  # ETH
        "DAI",  # DAI
        "USDC",  # USDC
    ],
    scope="session",
    autouse=True,
)
def token(request):
    yield Contract(token_addresses[request.param])


whale_addresses = {
    "WBTC": "0x73B14a78a0D396C521f954532d43fd5fFe385216",
    "WETH": "0x6202A3B0bE1D222971E93AaB084c6E584C29DB70",
    "DAI": "0x1337BedC9D22ecbe766dF105c9623922A27963EC",
    "USDC": "0xAD7b4C162707E0B2b5f6fdDbD3f8538A5fbA0d60",
}


@pytest.fixture(scope="session", autouse=True)
def token_whale(token):
    yield whale_addresses[token.symbol()]


token_prices = {
    "WBTC": 20_000,
    "WETH": 1_500,
    "DAI": 1,
    "USDC": 1,
}


@pytest.fixture(autouse=True, scope="function")
def amount(token, token_whale, user):
    # this will get the number of tokens (around $1m worth of token)
    base_amount = round(250_000 / token_prices[token.symbol()])
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
    token_address = token_addresses["WETH"]
    yield Contract(token_address)


@pytest.fixture
def usdc():
    token_address = token_addresses["USDC"]
    yield Contract(token_address)


@pytest.fixture
def weth_amount(user, weth):
    weth_amount = 10 ** weth.decimals()
    weth.transfer(user, weth_amount, {"from": whale_addresses["WETH"]})
    yield weth_amount


@pytest.fixture(scope="function", autouse=True)
def vault(pm, gov, rewards, guardian, management, token):
    Vault = pm(config["dependencies"][0]).Vault
    vault = guardian.deploy(Vault)
    vault.initialize(token, gov, rewards, "", "", guardian, management)
    vault.setDepositLimit(2**256 - 1, {"from": gov})
    vault.setManagement(management, {"from": gov})
    vault.setManagementFee(0, {"from": gov})
    yield vault


@pytest.fixture(scope="function")
def factory(strategist, vault, LevAaveFactory):
    yield strategist.deploy(LevAaveFactory, vault)


@pytest.fixture(scope="function")
def strategy(chain, keeper, vault, factory, gov, strategist, Strategy):
    strategy = Strategy.at(factory.original())
    strategy.setKeeper(keeper, {"from": strategist})

    vault.addStrategy(strategy, 10_000, 0, 2**256 - 1, 1_000, {"from": gov})
    chain.sleep(1)
    chain.mine()
    yield strategy


@pytest.fixture(scope="function")
def enable_healthcheck(strategy, gov):
    strategy.setHealthCheck("0x3d8F58774611676fd196D26149C71a9142C45296", {"from": gov})
    strategy.setDoHealthCheck(True, {"from": gov})
    yield True


@pytest.fixture(scope="function")
def enable_emode(strategy, gov):
    category = strategy.setEMode(True, True, {"from": gov}).return_value
    print("EMode category:", category)
    yield category


@pytest.fixture(scope="session")
def protocol_data_provider():
    yield Contract("0x69FA688f1Dc47d4B5d8029D5a35FB7a548310654")  # ProtocolDataProvider


@pytest.fixture(scope="function", autouse=True)
def set_min_max(strategy, token, management):
    strategy.setMinsAndMaxs(
        0.1 / token_prices[token.symbol()] * 10 ** token.decimals(),
        strategy.minRatio(),
        strategy.maxIterations(),
        {"from": management},
    )
    if token.address == token_addresses["DAI"]:
        strategy.setRewardBehavior(
            strategy.minRewardToSell(), True, True, {"from": management}
        )


@pytest.fixture(scope="session", autouse=True)
def RELATIVE_APPROX():
    yield 1e-5
