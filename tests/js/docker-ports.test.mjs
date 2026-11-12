import test from 'node:test';
import assert from 'node:assert/strict';
import {publishedPorts} from '../../herdr/mods/repo-portrait/docker-ports.js';
const service=(ports)=>[{Service:'web',Publishers:ports}];
const port=(extra={})=>({URL:'0.0.0.0',PublishedPort:6200,TargetPort:5173,Protocol:'tcp',...extra});
test('published port uses remote host, not wildcard or laptop localhost',()=>{
 const [p]=publishedPorts(service([port()]),'developer@server.example');
 assert.equal(p.port,6200);assert.equal(p.url,'http://server.example:6200');
 assert.equal(p.suggested,true);
 assert.equal(publishedPorts(service([port()]))[0].url,'http://localhost:6200');
});
test('remote loopback, databases, UDP and unpublished ports never invent web links',()=>{
 assert.equal(publishedPorts(service([port({URL:'127.0.0.1'})]),'server')[0].url,null);
 assert.equal(publishedPorts(service([port({TargetPort:5432})]))[0].url,null);
 assert.equal(publishedPorts(service([port({Protocol:'udp',TargetPort:80})]))[0].url,null);
 assert.deepEqual(publishedPorts(service([port({PublishedPort:0})])),[]);
 assert.deepEqual(publishedPorts([{Service:'db'}]),[]);
});
test('IPv6 formatting, explicit https and duplicate wildcard bindings',()=>{
 const p=publishedPorts(service([port({URL:'::',AppProtocol:'https'}),port({AppProtocol:'https'})]),'server.example');
 assert.equal(p.length,1);assert.equal(p[0].url,'https://server.example:6200');assert.equal(p[0].suggested,false);
 assert.equal(publishedPorts(service([port({URL:'2001:db8::1'})]))[0].url,'http://[2001:db8::1]:6200');
 assert.equal(publishedPorts(service([port()]),'invalid/host')[0].url,null);
});

test('declared application protocol overrides port-number guesses',()=>{
 assert.equal(publishedPorts(service([port({AppProtocol:'http',TargetPort:443})]))[0].url,'http://localhost:6200');
 assert.equal(publishedPorts(service([port({AppProtocol:'grpc',TargetPort:80})]))[0].url,null);
});
