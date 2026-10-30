// Read-only persistent client for one Ignition SDF service; no scene writes.
#include <ignition/transport/Node.hh>
#include <ignition/msgs/sdf_generator_config.pb.h>
#include <ignition/msgs/stringmsg.pb.h>
#include <ignition/msgs/empty.pb.h>
#include <ignition/msgs/scene.pb.h>
#include <google/protobuf/util/json_util.h>
#include <algorithm>
#include <chrono>
#include <iostream>
#include <string>
#include <thread>
#include <vector>
int main() {
  const std::string service="/world/default/generate_world_sdf";
  ignition::transport::Node node;
  bool listed=false;
  for (int i=0;i<50 && !listed;++i) {
    std::vector<std::string> names; node.ServiceList(names);
    listed=std::find(names.begin(),names.end(),service)!=names.end();
    if(!listed) std::this_thread::sleep_for(std::chrono::milliseconds(100));
  }
  std::cout<<"{\"event\":\"ready\",\"service_listed\":"<<(listed?"true":"false")<<"}"<<std::endl;
  if(!listed) return 2;
  std::string line; unsigned sequence=0;
  while(std::getline(std::cin,line)) {
    if(line=="QUIT") break;
    if(line!="GET" && line!="SCENE") return 3;
    ignition::msgs::SdfGeneratorConfig request;
    ignition::msgs::StringMsg response; bool result=false;
    auto began=std::chrono::steady_clock::now();
    bool executed=false;
    if(line=="GET") executed=node.Request(service,request,20000,response,result);
    else {
      ignition::msgs::Empty empty; ignition::msgs::Scene scene;
      executed=node.Request("/world/default/scene/info",empty,20000,scene,result);
      response.set_data(scene.DebugString());
    }
    auto elapsed=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-began).count();
    std::string json; auto status=google::protobuf::util::MessageToJsonString(response,&json);
    if(!status.ok()) return 4;
    std::cout<<"{\"sequence\":"<<++sequence<<",\"executed\":"<<(executed?"true":"false")<<",\"result\":"<<(result?"true":"false")<<",\"milliseconds\":"<<elapsed<<",\"response\":"<<json<<"}"<<std::endl;
  }
  return 0;
}
