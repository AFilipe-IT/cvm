# VM de validação — Ubuntu 22.04 LTS

Alvo real para a Fase C do [plano](../PLANO_V2.md): as dimensões de
**permissões** e **exposição** só se exercitam contra um sistema com serviços a
sério, ficheiros com donos e modos verdadeiros, e portas efectivamente à escuta.

## Porquê QEMU/KVM

Esta máquina não tem hipervisor instalado do lado do Windows, mas o WSL2 expõe
`/dev/kvm` com virtualização encaixada activa. A VM corre com aceleração nativa
a partir do próprio WSL — sem elevação, sem prompts de UAC, e portanto
inteiramente scriptável. O Multipass e o Hyper-V exigiriam passos manuais no
Windows a cada operação.

## Arrancar

Uma vez só, porque pedem palavra-passe:

```bash
sudo apt-get update && sudo apt-get install -y qemu-system-x86 qemu-utils cloud-image-utils
sudo usermod -aG kvm "$USER"
```

O grupo `kvm` só produz efeito depois de reiniciar o WSL. No PowerShell:

```powershell
wsl --shutdown
```

Depois, daqui:

```bash
./vm/provision.sh
```

O primeiro arranque descarrega ~650 MB e demora 2-4 minutos a provisionar. Os
seguintes são segundos. O script é idempotente — voltar a corrê-lo não repete
trabalho feito.

```bash
./vm/provision.sh --recreate   # deitar abaixo e reconstruir do zero
```

## O que a VM tem

Tudo está declarado em [`cloud-init/user-data`](cloud-init/user-data), que é a
definição do alvo: reconstruir do zero dá o mesmo sistema, sem estado
acumulado.

| Dimensão | Falha inserida | Onde |
|---|---|---|
| Configuração | `server_tokens on`, TLSv1/1.1 activos | `/etc/nginx/conf.d/cvm-target.conf` |
| Permissões | `/etc/shadow` a 0644 (CIS exige 0640) | `runcmd` |
| Permissões | `/etc/nginx/nginx.conf` a 0666 | `runcmd` |
| Exposição | `stub_status` a escutar em `0.0.0.0:8080` | `sites-available/exposed-status` |

**As falhas são deliberadas.** A VM é um alvo sintético atrás de NAT do
utilizador, com o SSH só em loopback. `/etc/cvm-target` marca-a como tal, para
que nenhum resultado desta máquina seja confundido com um sistema real.

## Reprodutibilidade

A imagem base é verificada contra o `SHA256SUMS` publicado pela Canonical e o
valor fica em `run/base-image.sha256`. A Canonical republica `current`
periodicamente: se o checksum deixar de bater depois de uma republicação, apaga
`images/` e volta a correr — mas regista o novo valor, porque muda a base dos
resultados.

Nada do que o script gera é versionado (ver `.gitignore`): as imagens têm GB e
reconstroem-se do zero a partir daqui.

## Acesso

```bash
ssh -i vm/run/id_ed25519 -p 2222 cvm@127.0.0.1
kill $(cat vm/run/qemu.pid)     # parar
```

O par de chaves é gerado por `provision.sh` e serve só esta VM. A consola série
fica em `run/console.log` — é onde se vê o que correu mal se a VM não arrancar.

Parâmetros por variável de ambiente: `CVM_VM_MEM` (4096), `CVM_VM_CPUS` (2),
`CVM_VM_SSH_PORT` (2222).
