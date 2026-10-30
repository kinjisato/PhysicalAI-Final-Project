# 第三者ソフトウェア・資産

旧調査の確認日: 2026-10-24。これはソース一式の公開範囲についての整理です。Dockerイメージ・モデル重み・取得tar・Fuelモデル本体は同梱しません。上流のライセンス確認と、実コンテナ内の全依存物の監査は区別します。

| 対象 / 配布元 | 使用版・固定状態 | ライセンスと表示 | このリポジトリでの扱い / 残件 |
|---|---|---|---|
| CRANE+ / [RT Corporation](https://github.com/rt-net/crane_plus/tree/19c1d6069126cd27488bf1bbefd410704bfc515d) | commit 19c1d6069126cd27488bf1bbefd410704bfc515d、package.xml 2.0.1、94ファイル | Apache-2.0。LICENSE・著作権表示・派生表示を保持 | 派生launchを同梱、ソースtarは取得のみ。全文はlicenses/crane_plus-Apache-2.0.txt。固定commitのtreeにはNOTICE名のファイルなしを確認 |
| ROS 2 / [rclcpp Humble](https://github.com/ros2/rclcpp/blob/humble/LICENSE) | Humble、パッケージ小版は未採取 | rclcppはApache-2.0。ROS全体を単一ライセンスとしない | 外部ベース依存。コードをこのリポジトリにコピーしない。実バイナリと関連パッケージの個別条件は構築後確認 |
| Ignition Gazebo / [gz-sim ign-gazebo6](https://github.com/gazebosim/gz-sim/blob/ign-gazebo6/LICENSE) | 6系、実パッケージ小版未採取 | Apache-2.0。著作権・LICENSE・該当NOTICEの保持 | 外部ベース依存。付属ライブラリは別条件を含み得る |
| MoveIt 2 / [Humble LICENSE](https://github.com/moveit/moveit2/blob/humble/LICENSE.txt) | Humble、実小版未採取 | 上流トップレベルはBSD-3-Clause。帰属・条件・免責を保持 | 外部ベース依存。プラグイン等まで一律BSDと断定しない |
| RViz / [Humble LICENSE](https://github.com/ros2/rviz/blob/humble/LICENSE) | Humble、実小版未採取 | 上流はClear BSD License。帰属・条件・免責を保持、特許許諾を含むと解釈しない | 外部ベース依存。Qt/OGRE等の条件は別途 |
| Dockerベース / airobotbook | Dockerfileのsha256:b58ec74c019aacd9ce4818fa25fc5a9e0a1f22f8c9cd1f5260994bf15cd9eb63 | 多数のOS/ROS/desktopパッケージの集合。包括的許諾を推定しない | Dockerfileは参照のみ、イメージの再配布なし。全体SBOM/個別copyrightの採取は未実施 |
| Ollama / [公式LICENSE](https://github.com/ollama/ollama/blob/main/LICENSE) | ollama/ollama:latest、可変。実バージョン未採取 | MIT。ソフトを再配布するときは著作権と許諾文が必要 | Dockerfileでビルド時取得。ソース/バイナリの同梱なし。CPUランタイムの依存条件は別途 |
| Qwen2.5:3b / [Qwen公式3B LICENSE](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/main/LICENSE) | モデルタグ可変、新専用環境では未取得 | Qwen Research License Agreement。非商用の研究・評価用途。商用は別許諾。再配布には契約文・指定NOTICE等が必要 | 重みを同梱しない。学術デモの条件を確認し、実際にpullしたモデルのlicense/digestを記録する。他サイズのApache-2.0と混同しない |
| Fuel Table / [公式メタデータ](https://fuel.gazebosim.org/1.0/OpenRobotics/models/Table) | 確認時version 4、URLはtip相当で可変 | CC0 1.0 Universalの宣言を確認 | 本体なし、SDF内のURLのみ。実キャッシュとの同一性は未確認 |
| Fuel Ground Plane / [公式メタデータ](https://fuel.gazebosim.org/1.0/OpenRobotics/models/Ground%20Plane) | 確認時version 5 | CC0 1.0 Universalの宣言を確認 | 同上 |
| Fuel Sun / [公式メタデータ](https://fuel.gazebosim.org/1.0/OpenRobotics/models/Sun) | 確認時version 3 | CC0 1.0 Universalの宣言を確認 | 同上 |

CC0の条件は [Creative Commons公式文書](https://creativecommons.org/publicdomain/zero/1.0/) を参照。model.configだけでは不明だったFuelの利用条件は、今回公式APIのlicense_name/license_urlにより確認しました。旧キャッシュ内の同名資産の版や条件まで確認したことにはなりません。

独自コードは [LICENSE_STATUS.md](../LICENSE_STATUS.md)。OSSライセンスの新規選択は代行していません。第三者の必要な法人著作権を個人情報除去の名目で消しません。CRANE+由来launchの既存ヘッダとApache全文を保持し、実行コードを変更していません。

## 2026-10-28の公開構成との差分

上表の旧調査のうち、Ollamaの可変latestという記述は今回の公開入口には適用しない。root Dockerfileとdependencies.lockでimage digest `5c6707fcf2e1a30cffe2ecb7e315584fc87747c389327e4bc711c4959aa1eecc` に固定した。QwenもMODEL_PINのlogical digest/6blob/manifestで固定し、既存RO volumeで全hash照合と新規二重推論を実施した。モデル重みの新規取得と再配布はしていない。

FuelはSun3 / Ground Plane5 / Table4の明示version URLから取得し、FUEL_PINSで測定済みfile hashを照合した。旧cacheとの形式/同一texture URI差を区別し、旧worldのURLを変更せずcache aliasで解決した。CRANE+固定commit94ファイルの取得・照合・構築も実施した。MoveIt move-group 2.5.7、Transport11.4.1 / Msgs8.7.0 devはcapacity probeで測定した。これらは上表の過去の未確認事項を更新する実行記録であり、依存ソフト全体のライセンス監査を新たに完了したとの主張ではない。

## 2026-10-29の新規取得確認

正式構成のOllamaは同じ固定image digestを使用し、実測versionは0.40.9。Qwenの6blob（重みを含む）は公開registryから新規取得し、MODEL_PINのbyte数/SHA256で照合した。Ollama用の索引だけはコンテナ内で生成し、固定論理manifestを参照する。モデル重みを公開ソースへ同梱しない。Fuelの3資産とCRANE+94ファイルも空のcacheへ公開URLから取得して照合した。

Ubuntuデスクトップは公開元imageに含まれるMATE/Marco、Terminator、fcitx/Mozc、TigerVNC、Supervisor、noVNC 1.4.0をそのまま利用する。これらを新規GUIへ置換せず、各ソフトのcopyright/licenseは元image内に残す。
