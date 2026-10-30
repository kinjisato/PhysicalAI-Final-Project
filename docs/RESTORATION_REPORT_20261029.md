# Ubuntu復元・第三者再現性の実測記録（2026-10-29）

ローカルでは代表タスク2件（青→黄→緑、および青→青→黄）の実行・Home復帰、未対応要求1件の安全拒否、停止・再開がPASS。公開GitHubからのcloneは、提出先URLが未提供のため未実施。したがって「GitHubからcloneした第三者で最終合格」とはまだ判定しない。別ホストと全28ケースの再試験も未実施。

## 従来環境と今回の差分

`pai_final_dev`と`pai_ros2`から取得した`/entrypoint.sh`はともにSHA256 `8d1bd9a18213c57f1ecfb1d066d7a1932efcfab6f8ce3a7fb8b3ae5a62b68341`。公開元イメージの同スクリプトもビルド中に照合した。

|構成|以前の実物|修正前の提出版|復元版|
|---|---|---|---|
|デスクトップ|MATE / Marco / mate-panel / Caja|Xtigervnc上にRViz/xtermのみ|公開元のMATE構成|
|ターミナル・日本語入力|Terminator / fcitx / Mozc|xterm|元のTerminator/fcitxを保持。日本語clipboard入力を実測|
|起動|`/entrypoint.sh`→tini/Supervisor|独自bootstrapでVNC直接起動|元entrypointを無改変で実行、SupervisorへROS/Qwen program追加|
|ブラウザ接続|`/usr/lib/novnc`、コンテナ80→ホスト6080|追加noVNC、6080→6080|元noVNC 1.4.0、80→6080。検証時は競合回避で6081|
|モデル|ローカル既存Volume|既存外部Volumeが既定|公開registryから6blobを新規取得しRO bind。小さな索引のみコンテナ内で作成|

制御・意味監査・安全検査・軌道・モデルID・Home基準の変更はない。`code/`の全ファイルは修正前とbyte一致。`CORE_PINS.json`、凍結40ファイル、runner関数/classのAST、`MODEL_PIN.json`も保持した。PUBLIC_MANIFESTは変更した配布/起動用ファイルに合わせて更新し、凍結pinを再定義していない。

## 変更ファイル

|ファイル|変更理由|
|---|---|
|`Dockerfile`|追加GUIのapt導入を廃止。公開親の元entrypoint/デスクトップを検査し、ROS/Qwenの追加部分だけ構築|
|`compose.yaml`|GUIを既定化、80番へ公開、新規取得モデルbindを既定化、コンテナ別ログ、healthcheck|
|`compose.gui.yaml`、`compose.model-bind.yaml`|旧呼び出し用の互換定義。既定構成と競合しない|
|`compose.model-volume.yaml`（新規）|明示した場合だけ既存VolumeをRO利用。正式取得経路では不要|
|`.env.example`|最終タグ・ポート・解像度を統一|
|`tools/container_bootstrap.sh`|元entrypointを起動、Supervisor追加、Terminatorショートカット、前回ログ保全|
|`tools/runtime_bootstrap.sh`（新規）|元デスクトップと並行してROS/Qwen・scene・安全prepareを起動。Ollama初回索引を分離|
|`tools/desktop_shell.sh`（新規）|Ubuntu内のROS環境設定、準備待ち、日本語入力、Gazebo partitionをサーバーと一致|
|`tools/manage.py`|最終imageタグ、既定モデルbind/ログ、停止済みコンテナのstart、80番と要求前readinessの検証|
|`tools/readiness.py`|コンテナの同一VM内での停止・再開を区別し、古いreadyを受理しない|
|`tests/test_distribution.py`|既定ログ・80番接続の配布契約へ更新|
|`README.md`|取得・build・GUI・日本語・Home・停止再開・障害対応を同じ構成へ統一|
|`docs/THIRD_PARTY_NOTICES.md`|実測したOllama版、新規モデル/依存取得、元デスクトップの扱いを追記|
|本記録、`PUBLIC_MANIFEST.json`|検証範囲と変更ファイルのSHA256を記録|

`Dockerfile.gui-overlay`と`tools/quick_browser_test.sh`は過去の増分調査用として保全し、正式手順には使用しない。

## 構築と再現性

公開ファイルだけを別ディレクトリへコピーし、空のcacheからCRANE+ commit `19c1d6069126cd27488bf1bbefd410704bfc515d`の94ファイルとFuel Sun3/Ground Plane5/Table4を公開URLで取得してhash照合した。Qwen重みを含む全6blobも公開registryから新規取得して、byte数/SHA256を確認した。別ディレクトリの検証にはその新規取得済みモデルファイルのhardlinkを使い、既存Volumeからのコピーや取り出しは行っていない。

この公開ソースだけのコピーから正式Dockerfileをbuildし、`pai-desktop:clean-20261029`を作成して実動作を確認した。親は公開固定のairobotbook/Ollamaだけであり、`pai_ros2_saved`や`pai-verify28`へのFROMはない。Dockerの公開親image層とbuild cacheは共有した。registryの固定manifest到達性も確認したが、base全層の再ダウンロード、no-cache build、別ホスト再現とは区別する。

## 実測PASS/FAIL

|検証|判定|証拠・限界|
|---|---|---|
|旧entrypoint一致・デスクトップ復元|PASS|保存/公開元/正式buildのSHA256一致、MATE/Marco/Terminatorの実画面|
|公開固定親からDocker build|PASS|`build.log`、`clean_build.log`|
|空cacheからCRANE+/Fuel取得|PASS|`clean_dependencies.log`、94ファイルと固定Fuelのhash|
|Qwen全6blob新規取得|PASS|`model_fetch_network.log`。既存Volumeは不使用|
|一体型コンテナ起動・安全prepare|PASS|`clean_startup.log`、新規prepare session。task goal 0|
|ブラウザのUbuntu/RViz/CRANE+/3対象表示|PASS|`browser_japanese_input.png`、`browser_robot_before_motion.png`、`browser_home_return.png`|
|Ubuntu内から日本語原文入力|PASS|clipboard→TerminatorのPaste。session原文と入力画面が一致|
|Qwen二重解釈/C03|PASS|2回とも青/黄/緑、C03 ready・verified|
|低速停止診断|PASS|当該要求の新規診断1goal、cancel/hold証跡|
|MoveIt/Gazeboで青→黄→緑→Home|PASS|新規session `869d96d8f8be4f298e35728f8f98af48`、task goal 4件すべて成功|
|Home復帰|PASS|青→黄→緑の最大joint誤差0.0018921340171987305 rad ≤ 0.025 rad|
|再開後のT02：青→青→黄→Home|PASS|session `87c04cfabfb346d9ae6bf755047909bf`。task goal 4件成功、Home誤差0.001431233206340669 rad。再訪離脱1.3931507553662326 rad ≥ 0.03 rad|
|実行証跡の整合性|PASS|成功2件と未対応拒否1件を検査。初回GUI失敗を含むclean全体の検査はINCOMPLETEとして別保存|
|未対応指示の安全拒否|PASS|「青を撮影して」→unsupported、Qwen2回、task/diagnostic goalとも0。session `665a8999e0f14470b2d555ca7e91352c`|
|最終作業ディレクトリからの起動・停止再開|PASS|`final_startup.log`、`final_stop.log`、`final_resume_verified.log`。新規init_startのreadyを確認、旧readyと前回ログを保全|
|Mozcの直接かな漢字変換|FAIL|元imageの変換エンジン起動エラー。clipboard経路の日本語入力はPASS|
|公開GitHub clone|未実施|URL未提供、作業ディレクトリに.git/remoteなし。接続先検索にも該当repoなし|
|別ホスト・base全層新規取得・全28ケース再試験|未実施|今回の代表実測から拡大解釈しない|

代表タスクのQwen実測は1回目171.85秒、2回目33.71秒。180秒の既存timeoutを変更していない。1回目は既存GUI検証コンテナとCPU競合していた。要求処理中でないことを確認して旧GUI検証コンテナを一時pauseし、最終検証後にunpause済み。削除/再起動はしない。

## 失敗と修正の記録

1. 最初の正式起動：Ollama 0.40.9が新しい索引`manifests-v2`をRO storeへ生成できず、`/api/tags`が500。prepareはHOLD、task/diagnostic goal 0。重みはROのまま、コンテナ内の小さな索引とblobへのsymlinkへ分離した。旧成功storeと比較し、wrapperではなく固定論理manifest `357c53…`をv2索引から参照させた。モデルpinや重みは変更しない。
2. 途中の起動用スクリプト更新が実行中の読み取りと競合し、v2起動でshell syntax error。task goal 0。失敗コンテナとログを保全し、以降は独立ソースコピーを用いて修正後のスクリプトを起動前に固定した。
3. 最初のGUI要求：`sudo`でUSERがrootとなり、Gazeboの既定partitionがサーバー側と異なってSDF service discoveryが失敗。Qwen/goalとも0でHOLD。`IGN_PARTITION=$(hostname):ubuntu`を入力用シェルに明示すると同じserviceを探索でき、その後の代表タスクが成功した。[Transport 11の公式仕様](https://gazebosim.org/api/transport/11/envvars.html)の既定hostname/usernameとも一致する。

4. 停止・再開の途中で準備完了前に追加ケースを投入してしまい、排他ロックで拒否されてケースドライバが検証コンテナを停止した。タスクgoal 0、当該T02はNOT_RUN、準備sessionはHOLDとして記録する。CLIのrun/cases/t02へ新規readiness確認を追加し、準備中要求がドライバ開始前に拒否されることと、その後のstart正常終了を再検証した。停止した既存lockの自動削除は行っていない。

失敗session `35b0ff6b8a0742829f899f0ee70d4dc0`も保全する。失敗を除いて全体PASSとは集計しない。各失敗は原因の修正後に新しい独立要求で再検証した。

## ログの所在と保全

**保全上の失敗：** 初回の正式起動は旧GUI検証と同じ`validation/`を使ってしまい、`bootstrap/ollama.log`、`ros.log`、`scene.log`、`prepare.log`および共有`baseline/preflight.json`・`environment/inspect.json`に上書きが発生した。上書き前の内容は完全復元できず、この点はユーザー指定のログ保全条件を満たせなかった。以後は既定を`validation/<コンテナ名>/`へ分離し、停止・再開前のbootstrapを`boots/`へ退避する。上書き後の初回ログと全失敗sessionは保全した。

ローカルの`validation/restoration_20261029/`に元ファイル、inspect、build/取得/起動ログ、画面証拠、`CORE_COMPARISON.json`、`CHANGED_FILES.json`、diff、`clean_runtime/sessions/`を保存した。Git管理外であり、個人パス付きinspectや重みを提出ソースへ含めない。既存image/Volume/開発コンテナ/過去sessionは削除していない。今回作成した失敗コンテナも停止状態で保全する。

## 最終課題の要件との対応

参照した手元の10/19版課題要件の抽出テキストに基づく確認。外部の提出規則の現行性を新たに保証するものではない。

|要件|対応|
|---|---|
|何らかのAIを利用（推論のみ可）|Qwenの実推論2回と生応答を保存、学習なし|
|ロボットに自由設定タスクを実行させる|日本語の訪問順をCRANE+がGazeboで実行、MoveIt軌道とROS結果を記録|
|使用コード一式|固定制御ソース、依存取得、Docker/Compose、検証入口を含む。重み/依存バイナリは公開取得方式|
|public GitHub URL|未達。提出先URLと公開clone検証が残る|
|1〜3分の実動作動画、倍速時の明記、YouTube URL|今回の環境復元作業では動画を新規作成・投稿していない。既存提出動画の適合性も今回未確認|
|概要・目的・工夫を記したPDF|今回のREADME/復元記録はPDF提出資料の代替ではない。既存PDFの適合性も今回未確認|
|成果物への個人情報混入回避|公開manifestの対象に検証inspect/ログ/モデルを入れない。提出時には動画/PDFも別途確認が必要|

したがって今回のコード環境の代表動作成功だけを、最終課題全提出物の提出完了や合格とは記載しない。

## このMacでの引き渡し状態

最終コンテナ`pai_github_all_desktop_20261029_final`は起動中。ソースは依頼された作業ディレクトリ、モデルはこの作業で公開取得した`.cache/model-root`のRO bind。接続先は[Ubuntuデスクトップ](http://127.0.0.1:6081/vnc.html)。旧GUI検証の6080番と既存資産は維持し、一時pauseも解除済み。

この既存最終コンテナの管理には同じ設定を使う（第三者の新規環境ではREADMEの既定値を使用）：

```sh
export PAI_PROJECT=pai_github_all_desktop_20261029_final
export PAI_CONTAINER=pai_github_all_desktop_20261029_final
export PAI_WEB_PORT=6081
python3 -B tools/manage.py inspect
python3 -B tools/manage.py stop
python3 -B tools/manage.py start
```

起動完了までは`up/start`の終了を待つ。準備中のrun/cases/t02はreadiness確認で拒否され、ドライバを開始しない。T02の実測は`final_T02_verified.log`と`validation/pai_github_all_desktop_20261029_final/batches/f172128722ff4ac2a0334f3f9e1cd439/`。先行した未実施T02の記録は別batchとして残る。

イメージ内の全公開ソースを含めた整合性検査も実行し、ソースbindなし・network noneで84ファイル/凍結40ファイル/モデル同定のPASSを確認した。最終結果後の文書・管理CLI追記も再buildして検査する。実測を完了した制御/モデル/ROS起動コードの変更はない。
