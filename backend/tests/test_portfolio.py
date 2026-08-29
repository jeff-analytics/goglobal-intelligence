from app.portfolio import parse_portfolio_bytes


def test_portfolio_csv_minimum_field():
    rows=parse_portfolio_bytes(b"product_name,sku,origin,target_markets\nWidget A,A1,USA,US;DE\n",filename="x.csv")
    assert rows[0]["title"]=="Widget A"
    assert rows[0]["markets"]==["US","DE"]
    assert rows[0]["errors"]==[]
