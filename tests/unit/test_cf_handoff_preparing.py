"""168d-fix-T2：Broker 存殼回報的 preparing，preparing_for 受 liveness 約束。"""
from core import cf_handoff as m


def test_register_shell_stores_preparing(monkeypatch):
    b = m.Broker()
    b.register_shell('k', ['javlibrary'], preparing=['fc-javten'])
    assert b.preparing_for('k') == ['fc-javten']
    assert b.sites_for('k') == ['javlibrary']          # sites_for 不受影響
    assert b.shell_info('k')['preparing'] == ['fc-javten']


def test_register_shell_without_preparing_defaults_empty():
    b = m.Broker()
    b.register_shell('k', ['javlibrary'])               # 舊呼叫形狀
    assert b.preparing_for('k') == []


def test_preparing_for_unregistered_is_empty():
    assert m.Broker().preparing_for('nobody') == []


def test_preparing_for_requires_fresh_shell(monkeypatch):
    clock = {'t': 1000.0}
    monkeypatch.setattr(m, '_now', lambda: clock['t'])
    b = m.Broker()
    b.register_shell('k', [], preparing=['fc-javten', 'javlibrary'])
    assert b.preparing_for('k') == ['fc-javten', 'javlibrary']      # 對照格：fresh 時有值
    clock['t'] += m.LIVENESS_S + 1
    assert b.preparing_for('k') == []
