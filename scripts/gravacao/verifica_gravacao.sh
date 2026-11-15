#!/usr/bin/env bash
# Pré-voo da gravação: confirma que a máquina reproduz os números da dissertação.
# Uso:  CASPAR_DB=$PWD/ccss.db bash assets/video/verifica_gravacao.sh [caminho-do-caspar]
# O argumento é o executável (por omissão `caspar`); num repo usa:
#   bash assets/video/verifica_gravacao.sh ".venv/bin/python -m cli.main"
set -u
CASPAR=${1:-caspar}
export COLUMNS=100
T=${TEST_TARGET:-test_target}
ok=0; bad=0

score() { $CASPAR scan "$1" 2>&1 | grep -oE '[0-9]+\.[0-9] / 10' | head -1 | cut -d' ' -f1; }
check() { # <ficheiro> <esperado> <rótulo>
  local got; got=$(score "$1")
  if [ "$got" = "$2" ]; then printf '  \033[32mOK\033[0m   %-34s %s\n' "$3" "$got"; ok=$((ok+1))
  else printf '  \033[31mFALHA\033[0m %-34s %s (esperado %s)\n' "$3" "${got:-sem score}" "$2"; bad=$((bad+1)); fi
}

echo "== base de conhecimento =="
$CASPAR targets 2>&1 | tail -3
echo
echo "== dez pares do corpus (vulnerável) =="
check "$T/pod_vulnerable.yaml"          10.0 "kubernetes"
check "$T/mysql_demo/my.cnf"             9.4 "mysql"
check "$T/Dockerfile.vulnerable"         9.0 "dockerfile"
check "$T/httpd.conf"                    8.5 "apache-httpd  (sensível ao fix GEL/GRL)"
check "$T/azure_storage_vulnerable.tf"   8.5 "azure-iac"
check "$T/ssh_demo/sshd_config"          8.5 "ssh"
check "$T/nginx.conf"                    7.5 "nginx"
check "$T/ubuntu_demo/sysctl.conf"       5.8 "ubuntu"
check "$T/redis_demo/redis.conf"         5.0 "redis"
check "$T/tomcat_demo/tomcat.conf"       5.0 "tomcat"
echo
echo "== contrapartes endurecidas (todas 0.0) =="
for f in pod_hardened.yaml mysql_hardened_demo/my.cnf Dockerfile.hardened httpd_hardened.conf \
         azure_storage_hardened.tf nginx_hardened.conf; do
  [ -f "$T/$f" ] && check "$T/$f" 0.0 "${f%%/*}"
done
echo
echo "== agregação de pior caso (chains fora do score) =="
$CASPAR scan "$T/httpd.conf" 2>&1 | grep -E "Highest finding" | head -1
echo
echo "== manifesto de reprodutibilidade =="
$CASPAR scan "$T/nginx.conf" 2>&1 | grep -o "reproducible:.*" | head -1
echo
echo "resultado: $ok ok, $bad falhas"
[ "$bad" -eq 0 ]
