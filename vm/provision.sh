#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# vm/provision.sh — cria a VM de validação do CVM (Ubuntu 22.04 LTS)
#
# Porquê QEMU/KVM e não Multipass ou Hyper-V: o WSL2 desta máquina expõe
# /dev/kvm com virtualização encaixada activa, portanto a VM corre com
# aceleração nativa a partir do próprio WSL, sem elevação no Windows e sem
# prompts de UAC. Isso é o que torna todo o processo scriptável.
#
# O script é idempotente: corre-o outra vez e não repete o que já está feito.
# Para começar do zero, apaga vm/images/ e vm/run/.
#
# Uso:
#   ./vm/provision.sh            # descarrega, prepara e arranca
#   ./vm/provision.sh --recreate # deita abaixo e reconstrói a imagem
# ---------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGES="$HERE/images"
RUN="$HERE/run"

RELEASE="jammy"                     # Ubuntu 22.04 LTS
BASE_IMG="$IMAGES/${RELEASE}-server-cloudimg-amd64.img"
BASE_URL="https://cloud-images.ubuntu.com/${RELEASE}/current/${RELEASE}-server-cloudimg-amd64.img"
SUMS_URL="https://cloud-images.ubuntu.com/${RELEASE}/current/SHA256SUMS"

DISK="$RUN/cvm-target.qcow2"
SEED="$RUN/seed.iso"
DISK_SIZE="20G"
MEM="${CVM_VM_MEM:-4096}"
CPUS="${CVM_VM_CPUS:-2}"
SSH_PORT="${CVM_VM_SSH_PORT:-2222}"
KEY="$RUN/id_ed25519"

die() { printf '\033[31merro:\033[0m %s\n' "$*" >&2; exit 1; }
say() { printf '\033[36m==>\033[0m %s\n' "$*"; }

# ── pré-requisitos ────────────────────────────────────────────────────
need_pkgs=()
command -v qemu-system-x86_64 >/dev/null || need_pkgs+=("qemu-system-x86")
command -v qemu-img           >/dev/null || need_pkgs+=("qemu-utils")
command -v cloud-localds      >/dev/null || need_pkgs+=("cloud-image-utils")

if ((${#need_pkgs[@]})); then
    cat >&2 <<EOF
Faltam pacotes. Corre isto (pede palavra-passe, por isso não o faço eu):

    sudo apt-get update && sudo apt-get install -y ${need_pkgs[*]}

EOF
    exit 1
fi

[[ -e /dev/kvm ]] || die "/dev/kvm não existe — sem aceleração, a VM seria demasiado lenta para ser útil."

ACCEL=(-enable-kvm -cpu host)
if [[ ! -r /dev/kvm || ! -w /dev/kvm ]]; then
    cat >&2 <<'EOF'
Sem acesso a /dev/kvm. Junta-te ao grupo kvm (uma vez só):

    sudo usermod -aG kvm "$USER"

e depois reinicia o WSL a partir do PowerShell: wsl --shutdown
EOF
    exit 1
fi

[[ "${1:-}" == "--recreate" ]] && { say "a remover a imagem anterior"; rm -f "$DISK" "$SEED"; }

mkdir -p "$IMAGES" "$RUN"

# ── imagem base ───────────────────────────────────────────────────────
if [[ ! -f "$BASE_IMG" ]]; then
    say "a descarregar a cloud image do Ubuntu ${RELEASE} (~650 MB)"
    curl -fL --progress-bar -o "$BASE_IMG.part" "$BASE_URL"
    mv "$BASE_IMG.part" "$BASE_IMG"
else
    say "cloud image já presente: $(basename "$BASE_IMG")"
fi

# A imagem é a base de todos os resultados de validação, por isso o checksum
# é verificado contra o SHA256SUMS publicado e registado no manifesto.
say "a verificar o checksum contra o SHA256SUMS da Canonical"
expected="$(curl -fsSL "$SUMS_URL" | awk -v f="*${RELEASE}-server-cloudimg-amd64.img" '$2==f{print $1}')"
actual="$(sha256sum "$BASE_IMG" | cut -d' ' -f1)"
[[ -n "$expected" ]] || die "não consegui obter o checksum publicado."
if [[ "$expected" != "$actual" ]]; then
    die "checksum não bate. esperado=$expected obtido=$actual
A imagem pode estar corrompida ou desactualizada (a Canonical republica 'current').
Apaga $BASE_IMG e corre outra vez."
fi
printf '%s  %s\n' "$actual" "$(basename "$BASE_IMG")" > "$RUN/base-image.sha256"

# ── chave SSH ─────────────────────────────────────────────────────────
if [[ ! -f "$KEY" ]]; then
    say "a gerar par de chaves só para esta VM"
    ssh-keygen -t ed25519 -N '' -C "cvm-validation-target" -f "$KEY" >/dev/null
fi

# ── seed do cloud-init ────────────────────────────────────────────────
if [[ ! -f "$SEED" ]]; then
    say "a construir o seed do cloud-init"
    userdata="$RUN/user-data"
    sed "s|SSH_PUBKEY_PLACEHOLDER|$(cat "$KEY.pub")|" \
        "$HERE/cloud-init/user-data" > "$userdata"
    printf 'instance-id: cvm-target-01\nlocal-hostname: cvm-target-u2204\n' \
        > "$RUN/meta-data"
    cloud-localds "$SEED" "$userdata" "$RUN/meta-data"
fi

# ── disco ─────────────────────────────────────────────────────────────
if [[ ! -f "$DISK" ]]; then
    say "a criar o disco (overlay sobre a imagem base, $DISK_SIZE)"
    qemu-img create -f qcow2 -F qcow2 -b "$BASE_IMG" "$DISK" "$DISK_SIZE" >/dev/null
fi

# ── arranque ──────────────────────────────────────────────────────────
if pgrep -f "cvm-target.qcow2" >/dev/null; then
    say "a VM já está a correr"
else
    say "a arrancar a VM (${CPUS} vCPU, ${MEM} MB, SSH em localhost:${SSH_PORT})"
    qemu-system-x86_64 \
        "${ACCEL[@]}" \
        -m "$MEM" -smp "$CPUS" \
        -drive "file=$DISK,if=virtio,format=qcow2" \
        -drive "file=$SEED,if=virtio,format=raw" \
        -netdev "user,id=n0,hostfwd=tcp:127.0.0.1:${SSH_PORT}-:22" \
        -device virtio-net-pci,netdev=n0 \
        -display none -daemonize \
        -serial "file:$RUN/console.log" \
        -pidfile "$RUN/qemu.pid"
fi

# ── esperar pelo cloud-init ───────────────────────────────────────────
say "à espera que o cloud-init termine (primeiro arranque leva ~2-4 min)"
ssh_opts=(-i "$KEY" -p "$SSH_PORT" -o StrictHostKeyChecking=no
          -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR
          -o ConnectTimeout=5)

for i in $(seq 1 120); do
    if ssh "${ssh_opts[@]}" cvm@127.0.0.1 'test -f /var/lib/cvm-provisioned' 2>/dev/null; then
        say "VM pronta."
        cat <<EOF

  ssh -i $KEY -p $SSH_PORT cvm@127.0.0.1

  parar:    kill \$(cat $RUN/qemu.pid)
  consola:  $RUN/console.log
  recriar:  $0 --recreate

EOF
        exit 0
    fi
    sleep 5
done

die "a VM não ficou pronta em 10 minutos. Vê $RUN/console.log"
