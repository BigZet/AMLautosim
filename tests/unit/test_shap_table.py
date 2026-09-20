from src.aml_workshop_simulator.ui.nicegui.shap_result import shap_table_rows


def test_shap_orders_positive_contributions_before_larger_negative_ones():
    factors = [dict(feature=name, title=name, value=1, contribution=value)
               for name, value in [('negative', -9), ('small', .2), ('zero', 0), ('large', 2), ('tiny', .000001)]]
    rows = shap_table_rows(factors)
    assert [r['feature'] for r in rows] == ['large', 'small', 'tiny', 'zero', 'negative']
    assert rows[0]['impact'] == '+2,0000'
    assert rows[2]['impact'] == '+<0,0001'
    assert rows[-1]['impact'] == '-9,0000'
    assert all(r['value'] == '1' for r in rows)
