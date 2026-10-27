from app.strategy.range_break_even import initial_buy_stop_loss, initial_sell_stop_loss


def test_initial_stop_loss_independent_of_reference():
    assert initial_buy_stop_loss(4018.11, 1.00) == 4017.11
    assert initial_sell_stop_loss(4016.00, 1.00) == 4017.00