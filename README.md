# Physical AI：Ubuntu内で日本語指示からCRANE+を操作する

Ubuntu 22.04 / MATEの従来デスクトップをブラウザで開き、Terminatorから日本語でCRANE+に指示する。Qwen 2.5 3Bが独立に2回解釈し、Schema/C03安全検証後にMoveIt 2 / ROS 2 Humble / Gazeboで非接触の対象訪問を実行し、Homeへ戻る。一体型コンテナで完結する。A=青、B=黄、C=緑。実機操作、把持や物体移動は対象外。

保存イメージや過去コンテナ、既存のモデルVolumeは不要。公開固定イメージ、固定CRANE+ソース、Fuel資産、固定モデルblobを取得する。元の `/entrypoint.sh`、MATE/Marco、fcitx/Mozc、TigerVNC、Supervisor、`/usr/lib/novnc`を利用し、コンテナ80番をMac/Linuxの6080番へ公開する。独自GUIへの置換は行わない。

## 現在の確認状況

2026-10-29、公開固定親からのbuild、新規モデル取得、Ubuntu内の日本語入力→Qwen二重解釈→C03→青/黄/緑への訪問→Home復帰、再開後の青/青/黄への再訪、未対応要求のgoal 0拒否を実測した。最終検証の判定は [復元検証記録](docs/RESTORATION_REPORT_20261029.md) を参照。未実施をPASSとは扱わない。公開GitHub URLは未提供のため、GitHubからのclone実証は未実施。

## 1. 前提条件とclone

- Git、Python 3.10以上、Docker EngineまたはDocker Desktop、Docker Compose v2。ホストPythonの追加pipライブラリは不要。
- コンテナはlinux/amd64。Mac Apple SiliconはDocker Desktopのamd64互換実行を有効にする。native arm64/Windows/実機は未検証。
- 推奨：CPU 8コア、ホストRAM 16GiB、Docker VM RAM 8GiB以上、初回空きディスク50GiB以上。モデルは約1.93GB。コンテナ上限RAM 7GiB、追加swapなし。CPU互換実行では推論が遅くなる。
- 初回はDocker Hub、GitHub/codeload、fuel.gazebosim.org、registry.ollama.aiとredirect先へのHTTPS接続が必要。
- デスクトップはホストの127.0.0.1のみへ公開する。既定パスワードubuntu。ROSはdomain 42、localhost限定、実機デバイス・host networkは使用しない。

提出先URLは未確定。公開後の実URLを以下へ指定する。

```sh
git clone <提出先GitHubリポジトリURL> physical-ai
cd physical-ai
python3 -B tools/verify_source.py
python3 -B tests/test_release.py
python3 -B tests/test_distribution.py
```

以後はREADMEのあるディレクトリで実行する。ZIP取得でも同じ構成で利用できる。`verify_source.py`は全公開ファイルのSHA256、凍結制御40ファイル、runner関数/classのAST、モデル同定値、Python/JSON構文を検査する。ハッシュ不一致時は停止する。

## 2. ロボット・依存データを取得

```sh
python3 -B tools/fetch_dependencies.py
```

CRANE+ commit `19c1d6069126cd27488bf1bbefd410704bfc515d` の94ファイルをSHA256照合する。Fuel Sun 3 / Ground Plane 5 / Table 4は固定URLから取得し、許可されたファイルhashだけを認める。取得先はGit管理外の`.cache/vendor`と`.cache/fuel`。URL/版は`docker/dependencies.lock.json`、ファイルhashは`docker/FUEL_PINS.json`にある。旧Fuel hostnameは検証済みcacheのsymlinkで解決し、worldや衝突条件を変更しない。

## 3. Qwen 2.5 3Bを新規取得

[第三者表示とモデル利用条件](docs/THIRD_PARTY_NOTICES.md)を確認した上で実行する。

```sh
python3 -B tools/fetch_model.py --accept-model-license
```

正式モデルIDは`qwen2.5:3b`。`code/MODEL_PIN.json`と`docker/qwen_manifest.json`に固定した6blob、byte数、SHA256を使用する。論理digestは`357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`。可変タグの`ollama pull`へ置換しない。取得先`.cache/model-root/models`は起動時に読み取り専用でマウントする。Ollamaが初回生成する小さな索引だけをコンテナ内の`/opt/pai_runtime/ollama_models`へ置き、blobは元storeをsymlink参照する。モデルはGit/Docker imageに含めない。既存Volumeや`~/.ollama`は変更しない。

中断した`.part`は自動上書きしない。通信を復旧し、部分ファイルを別名で保全してから再取得する。不一致blobを無視しない。`--metadata-only`は重みのない通信検査であり、起動用には使えない。

## 4. 公開Dockerfileからビルド

```sh
docker pull --platform linux/amd64 airobotbook/ros2-desktop-ai-robot-book-humble@sha256:b58ec74c019aacd9ce4818fa25fc5a9e0a1f22f8c9cd1f5260994bf15cd9eb63
docker pull --platform linux/amd64 ollama/ollama@sha256:5c6707fcf2e1a30cffe2ecb7e315584fc87747c389327e4bc711c4959aa1eecc
python3 -B tools/manage.py build
```

生成タグは`pai-desktop:20261029`。公開元イメージから既存Ubuntu/ROS/MoveIt/Gazebo/MATEを利用し、固定Ollama CPUライブラリ、固定CRANE+のcolcon build、SDF RPC workerを追加する。GUIのapt追加やローカル保存イメージへのFROMは不要。元`/entrypoint.sh`のSHA256も照合する。既存ビルドcacheは利用し得るため、別ホストでの全層取得とは区別する。

## 5. 一体型コンテナを起動し、ブラウザで接続

```sh
export PAI_PROJECT=pai_github_all_desktop_20261029
export PAI_CONTAINER=pai_github_all_desktop_20261029
export PAI_IMAGE=pai-desktop:20261029
export PAI_WEB_PORT=6080
python3 -B tools/manage.py up
python3 -B tools/manage.py inspect
```

[Ubuntuデスクトップを開く](http://127.0.0.1:6080/vnc.html)。Connectを押し、求められたらパスワード`ubuntu`を入力する。従来と同じMATEパネル、移動・リサイズできるウィンドウ、Terminator、fcitx/Mozcを使用できる。Macの画面共有や追加VNCアプリは不要。

`up/start`が完了する前に別のrun/casesを実行しない。準備中要求はCLIでも拒否する。起動にはROS起動、シーン生成、モデルhash照合、安全prepareが含まれる。通常5分以内を目安とする。Healthがhealthyになり、Terminatorに`日本語指示 >`が出るまで待つ。起動だけではタスク軌道を送らない。RVizにCRANE+と対象物が出ていることを確認する。Gazeboはserverとして動き、表示・操作はRVizを使用する。

6080が既に使用中なら`export PAI_WEB_PORT=6081`を起動前に指定して、同じ番号のURLを開く。既存コンテナを上書きしない。同名がある場合は`PAI_PROJECT`と`PAI_CONTAINER`を新しい`pai_github_all_`始まりの名前にする。結果出力は既定の`validation/$PAI_CONTAINER/`。別の保存先は`PAI_VALIDATION`でリポジトリ外へ指定する。

## 6. Ubuntu内から日本語で動かす

自動表示されるPhysical-AI Terminatorへ1行ずつ入力する。

```text
青、黄、緑の順番に近づいて
青、青、黄の順に点検して
青と黄色を見て。緑は見なくていい
```

日本語IMEは元イメージのfcitx/Mozcを保持している。ただし今回のMac amd64互換実行ではMozc変換エンジンのエラーを観測した。表示された場合はOKで閉じ、noVNCサイドバーのClipboardへ原文を貼り付け、UbuntuのTerminatorで右クリック→Paste、またはCtrl+Shift+Vを使う。`exit`で入力画面を終了し、同じウィンドウでシェルを使用できる。デスクトップのPhysical AI gui/shellから再び開ける。

RVizの現在のロボット姿勢が各色の対象へ順番に変化し、最後にHomeへ戻ることを観察する。Qwenはtemperature 0、seed 0/1で2回解釈し、Schema/C03・原文照合・二重一致・単回使用ticket後にMoveItで全経路を検査する。許可後には既存の低速停止診断を1回実行し、その後に対象訪問とHomeを行う。Home最大joint誤差0.025rad、同一対象の再訪離脱0.03radを維持する。制御ロジック・モデルID・安全条件は変更しない。

対応は色の訪問順、回数、再訪、除外、訂正。未登録色は勝手に置換しない。`青を撮影して`など未対応要求は安全拒否し、タスクgoalは0になる。曖昧な指示や解釈不一致も安全停止し得る。安全拒否をタスク成功とは記録しない。失敗・HOLDの場合はログを確認し、自動再試行や自動Homeを行わない。

ホストから同じ入口を使う場合：

```sh
python3 -B tools/manage.py run --text '青、黄、緑の順番に近づいて'
python3 -B tools/verify_session.py "validation/$PAI_CONTAINER"
```

`validation/$PAI_CONTAINER/sessions/<UUID>/`に原文、Qwen生応答2本、C03判定、MoveIt軌道、ROS goal/controller結果、到達・Home証跡が保存される。GUIとホストからの同時要求は拒否する。期待表を推論へ渡さない。

28ケースの追加検証（時間を要する）：

```sh
python3 -B tools/manage.py cases --case T02
python3 -B tools/manage.py cases --all
```

入力は`cases/inputs_28.json`、期待表は実行後評価専用の`tests/expected_28.json`。成功、安全拒否、失敗、未実施を区別する。

## 7. 終了・再開

実行が完了してHomeへ戻ったことを確認してから停止する。

```sh
python3 -B tools/manage.py stop
# 同じexport設定で、停止済みの今回のコンテナを再開する：
python3 -B tools/manage.py start
```

停止・再開は指定したlabel付きコンテナだけを対象にする。既に動作中なら再起動しない。起動ごとにreadinessを新規確認し、前回のマーカーを保全する。コードやDockerfileを変更した後は再buildし、新しいコンテナ名で`up`する。削除/down/prune、既存モデルの変更は自動で行わない。

## トラブルシューティング

- **ブラウザが開かない**：`docker ps`で`127.0.0.1:6080->80/tcp`を確認する。`docker logs "$PAI_CONTAINER"`、`validation/$PAI_CONTAINER/bootstrap/runtime.stderr`、コンテナ内`/var/log/supervisor/`を確認する。
- **黒画面・ウィンドウを動かせない**：コンテナ内`ps -ef`で`mate-session`、`marco`、`mate-panel`を確認する。`/entrypoint.sh`のhash不一致は別のGUIを追加せず、指定公開baseを使う。
- **ターミナルが準備待ち**：`validation/$PAI_CONTAINER/bootstrap/runtime.log`、`scene.log`、`prepare.log`、`ros.log`、`ollama.log`を読む。healthだけでロボット動作成功とは判定しない。
- **モデルがない/hash不一致**：手順3を完了する。`--metadata-only`では不足。モデルpinの変更や別モデルで代用しない。
- **Fuel/robot取得失敗**：固定URLへのHTTPSと空き容量を確認する。不一致データへの上書きをしない。
- **RVizに対象物がない**：scene/prepareログ、Fixed Frame、PlanningScene表示を確認する。未表示をPASSにしない。
- **Qwen timeout/安全停止**：180秒の推論timeout、安全監査閾値は元コードどおり。低速CPU、メモリ不足、解釈不一致の証跡を区別する。自動のseed選別や安全緩和はしない。
- **Gazebo TransportNoReply/Host unreachable**：`scene.log`とsessionのtransport/exceptionを保全する。既知の長時間運転課題で、復旧成功を未確認のまま次の動作へ進めない。
- **容量不足**：初回50GiBを目安に確保する。管理CLIはホスト残量2GiBを監視する。既存イメージ/Volume/ログの整理は自動実行しない。

## 権利・適合性・制約

[第三者表示](docs/THIRD_PARTY_NOTICES.md)、[独自コードの権利状態](LICENSE_STATUS.md)、[復元の差分と検証記録](docs/RESTORATION_REPORT_20261029.md)を参照。元の全28ケース成功、別ホスト再現、公開GitHub clone成功を未実施のまま主張しない。GPU、実機、把持、撮影、異常診断は範囲外。本番採用HOLD。

`Dockerfile.gui-overlay`と`tools/quick_browser_test.sh`は過去のローカル増分調査用として保全している。上の正式手順では使用しない。任意の既存モデルVolumeを明示的に利用する場合だけ`PAI_MODEL_VOLUME`と`compose.model-volume.yaml`を使用できるが、その経路は新規モデル取得の検証には含めない。
