"""TomTom live traffic integration contract tests (network requests mocked)."""
import json
import pytest
from app.georoutes import estimate_travel, RoutingUnavailable


def test_missing_key_disables_live_eta():
    with pytest.raises(RoutingUnavailable, match='not configured'):
        estimate_travel(12.9716, 77.5946, 12.9352, 77.6245, '')


def test_tomtom_traffic_time_road_distance_geometry(monkeypatch):
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, *args):
            return json.dumps({'routes':[{'summary':{
                'travelTimeInSeconds':1235, 'lengthInMeters':6850,'trafficDelayInSeconds':245},
                'legs':[{'points':[{'latitude':12.9716,'longitude':77.5946},
                                   {'latitude':12.95,'longitude':77.61},
                                   {'latitude':12.9352,'longitude':77.6245}]}]}]}).encode()
    def fake_open(req, timeout):
        assert req.full_url.startswith('https://api.tomtom.com/routing/1/calculateRoute/12.971600,77.594600:12.935200,77.624500/json?')
        assert 'traffic=true' in req.full_url
        assert 'travelMode=car' in req.full_url
        assert 'key=test-server-key' in req.full_url
        assert timeout<=10
        return FakeResponse()
    monkeypatch.setattr('app.georoutes.urlopen',fake_open)
    result=estimate_travel(12.9716,77.5946,12.9352,77.6245,'test-server-key')
    assert result['eta_minutes']==21
    assert result['distance_km']==6.85
    assert result['traffic_delay_minutes']==5
    assert result['route_points']==[[12.9716,77.5946],[12.95,77.61],[12.9352,77.6245]]
    assert result['source']=='tomtom_live_traffic'
    assert result['traffic_aware'] is True


def test_tomtom_provider_failure_never_invents_eta(monkeypatch):
    from urllib.error import URLError
    def fail(*args,**kwargs): raise URLError('offline')
    monkeypatch.setattr('app.georoutes.urlopen',fail)
    with pytest.raises(RoutingUnavailable,match='appointment is unchanged'):
        estimate_travel(12.97,77.59,12.93,77.62,'configured-key')


def test_invalid_coordinates_fail_without_network():
    with pytest.raises(RoutingUnavailable,match='invalid'):
        estimate_travel(110,78,12,77,'a-key')
