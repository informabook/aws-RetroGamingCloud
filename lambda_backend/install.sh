#!/bin/bash
# --- SCRIPT V8 (FIX APT LOCK + CADDY) ---
shutdown -P +60
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1

echo ">>> [1/6] NETTOYAGE DES VERROUS (FORCE)"
# On attend un peu que le reseau soit pret
sleep 5
# On tue les mises a jour auto qui bloquent tout
systemctl stop apt-daily.timer
systemctl stop apt-daily-upgrade.timer
killall apt apt-get unattended-upgr
rm /var/lib/apt/lists/lock
rm /var/cache/apt/archives/lock
rm /var/lib/dpkg/lock*
dpkg --configure -a

echo ">>> [2/6] INSTALLATION CADDY & OUTILS"
export DEBIAN_FRONTEND=noninteractive
export PATH=$PATH:/snap/bin

# Boucle de retry pour etre sur que l'install passe
n=0
until [ "$n" -ge 5 ]
do
   apt-get update -y && \
   apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl unzip wget && \
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg && \
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list && \
   apt-get update -y && \
   apt-get install -y caddy && \
   break
   n=$((n+1)) 
   echo ">>> Echec apt-get... retry dans 5s..."
   sleep 5
done

echo ">>> [3/6] DOMAINE SSLIP.IO"
PUBLIC_IP=$(curl -s http://checkip.amazonaws.com)
DASHED_IP=${PUBLIC_IP//./-}
DOMAIN="${DASHED_IP}.sslip.io"
echo "Domaine: $DOMAIN"

echo ">>> [4/6] CONFIGURATION CADDY"
# On ecrase la config par defaut
cat <<EOF > /etc/caddy/Caddyfile
$DOMAIN {
    reverse_proxy localhost:3000
}
EOF
systemctl reload caddy
systemctl enable caddy

echo ">>> [5/6] RECUPERATION JEU & COEUR"
rm -rf /data/roms /data/cores
mkdir -p /data/roms /data/cores
chmod -R 777 /data

aws s3 cp "s3://{{BUCKET}}/{{KEY}}" "/data/roms/game.rom"

CORE_URL="https://buildbot.libretro.com/nightly/linux/x86_64/latest/{{CORE}}_libretro.so.zip"
wget -q -O /tmp/core.zip "$CORE_URL"
unzip -o /tmp/core.zip -d /data/cores/
rm /tmp/core.zip
chmod -R 777 /data

echo ">>> [6/6] LANCEMENT RETROARCH"
docker rm -f retroarch || true

# Lancement sur port 3000 (Caddy fera le pont 443 -> 3000)
docker run -d \
  --name=retroarch \
  --restart=always \
  --net=host \
  --privileged \
  -e PUID=1000 \
  -e PGID=1000 \
  -e TZ=Europe/Paris \
  -v /data:/data \
  lscr.io/linuxserver/retroarch:latest

sleep 10
docker exec retroarch pkill retroarch || true
sleep 2
docker exec -d -e DISPLAY=:1 retroarch retroarch -f -L /data/cores/{{CORE}}_libretro.so /data/roms/game.rom

echo ">>> SUCCES - PRET SUR https://$DOMAIN <<<"