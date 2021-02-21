docker build . -t localhost:32000/evohome-exporter:registry
docker push localhost:32000/evohome-exporter:registry
kubectl rollout restart deploy evohome-deploy -n evohome
kubectl logs -l app=evohome-exporter -n evohome -f
