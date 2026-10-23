"""168d-fix-T2：Broker 存殼回報的 preparing，preparing_for 受 liveness 約束。"""
from core import cf_handoff as m


def test_register_shell_stores_preparing(monkeypatch):
    b = m.Broker()
    b.register_shell('k', ['javlibrary'], preparing=['fc-javten'])
    assert b.preparing_for('k') == ['fc-javten']
    assert b.sites_for('k') == ['javlibrary']          # sites_for 不受影響
    assert b.shell_info('k')['preparing'] == ['fc-javten']


