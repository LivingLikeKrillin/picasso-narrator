import copy
import json
import pytest
from receiver.station import compose_station, explain_station, record_station

def evidence():
 return {"schema":"ops.station.evidence/1","authority":"deterministic-ops","explanationMayChangeState":False,"run":{"runId":"run-1","stationId":"inspection-1","state":"REVIEW_REQUIRED","reason":"현장 신호 관측 불명","receiptId":"receipt-1","revision":4,"attempt":0,"payload":{"interfaceId":"inspect","interfaceVersion":1,"expectedDeploymentVersion":2}},"events":[{"state":"REVIEW_REQUIRED","reason":"현장 신호 관측 불명","actor":"system/station","recordedAt":"2026-10-12T00:00:00Z","context":None}]}

def test_station_rejects_unknown_schema_before_generation():
 value=evidence();value['schema']='incident/5'
 with pytest.raises(ValueError):explain_station(value,lambda *a,**k:pytest.fail('must not call'))

def test_station_composition_preserves_unknown_and_original_facts():
 value=evidence();before=copy.deepcopy(value);query=compose_station(value)
 assert 'REVIEW_REQUIRED' in query and 'null' in query and 'inspection-1' in query
 assert value==before and '물리 완료' in query

def test_station_explanation_calls_once_and_retains_verified_citations():
 calls=[]
 def search(query):calls.append(query);return 200,{'success':True,'data':{'answer':'관측 확인 필요','citations':[{'verified':True,'quote':'a'}]}}
 result=explain_station(evidence(),search)
 assert len(calls)==1 and result['outcome']=='GIVEN' and result['authority']=='explanation-only'
 assert result['explanationMayChangeState'] is False and result['sourceState']=='REVIEW_REQUIRED'

def test_station_unverified_citations_are_not_evidence():
 result=explain_station(evidence(),lambda q:(200,{'success':True,'data':{'answer':'x','citations':[{'verified':False}]}}))
 assert result['outcome']=='UNCITED' and result['citations']==[]

def test_station_generation_failure_preserves_deterministic_state():
 result=explain_station(evidence(),lambda q:(503,{'detail':'offline'}))
 assert result['outcome']=='GENERATION_FAILED' and result['sourceState']=='REVIEW_REQUIRED'

def test_station_same_evidence_record_does_not_query_again(tmp_path):
 source=tmp_path/'source.json';source.write_text(json.dumps(evidence()),encoding='utf-8');calls=[]
 def search(q):calls.append(q);return 200,{'success':True,'data':{'abstained':True,'citations':[]}}
 first=record_station(source,tmp_path/'out',search);second=record_station(source,tmp_path/'out',search)
 assert first==second and len(calls)==1 and first['outcome']=='NO_EVIDENCE'
