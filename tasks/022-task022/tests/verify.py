#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Transition-state validation and conformer selection.
"""Scientific grader for P04 cases 01/02/03/05/06.

The checks read the public output contract and compare machine-readable submitted
results to independently frozen tables. Candidate parsing faults score zero; damaged
inputs, references, or grader dependencies invalidate the run without a reward.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

HARTREE_KCAL = 627.509
EXPECTED_CRITERIA = [('audit_table_covers_deposit', 'L1'), ('mode_count_and_classification_consistent', 'L2'), ('saddle_minimum_partition_reproduced', 'L3'), ('levels_and_electronic_states_identified', 'L3'), ('conformer_window_applied_explicitly', 'L3'), ('isomer_barriers_reproduced', 'L3')]
PINNED_REFERENCES: dict[str, str] = {'derived_conformer_members.csv': 'sha256:1d5f2415bf83a60b712832afcdba1360f7e93dd7621eb5ef917c12e4d163431a', 'derived_conformer_spreads.csv': 'sha256:1c7196f17c5dbc9c6da068666670829caf0a05e42843102bd848ec2bbe501472', 'derived_si_table7_isomer_barriers.csv': 'sha256:16451c0b08c5592cf1da65b6554d7bbee891999a76aaa34c0f4a71876052c7c3', 'native_gaussian_census.csv': 'sha256:e2c0602a21004fb542157ea259a94f5ada1d511686a721af2ba3196a960589e4'}
PINNED_ASSET_REFS: dict[str, str] = {'assets/41467_2023_40675_MOESM1_ESM.docx': 'sha256:52c8854e125cac6ea714c61a4e711fea66565cef62d0f176511e819e59fd568a', 'assets/41467_2023_40675_MOESM3_ESM.xlsx': 'sha256:69969f05b7fb9b75335737bfc4e65cd49218d75da632197d929f6196784b67f1', 'assets/Figure2/P-C2/P-C2-DFT-Conf2.log': 'sha256:50ae6c7d73ccda3fe7ffaff0c8b841860a58c447d93a3647e2007c30108a0b02', 'assets/Figure2/P-C2/P-C2-DFT-Conf3.log': 'sha256:99f153d695d5603feeeb599a2db60482a5075aabbcdeee21c1cbfd8a4de162fb', 'assets/Figure2/P-C2/P-C2-DFT-Conf4.log': 'sha256:813e94472c40c0e9d59bd02f4ba39f37f1fbc8c2717c14e9247ecf7998be7367', 'assets/Figure2/P-C2/P-C2-DFT-Conf5.log': 'sha256:b355430fd15120657301ef4f8686d967a4e7ba931110f6dacd0da1a307c623d4', 'assets/Figure2/P-C2/P-C2-DFT-Conf6.log': 'sha256:97f85e8b7f0a3b70e6b855c4fe5697c7d51dc3878359871d45d5c2b36b3242d7', 'assets/Figure2/P-C2/P-C2-DFT-Conf7.log': 'sha256:8a92a795561cc1c65ccc2b3a3437789edd58ae8ed9413556670eebe00f5b2060', 'assets/Figure2/P-C2/P-C2-DFT-Conf8.log': 'sha256:590c31f19006a8220092705a5c2f7126c1f6a708306eb6dace541e237416f5de', 'assets/Figure2/P-C2/P-C2-DFT.log': 'sha256:249341d49148b71394d84ff7b8f03daf17168c7d2ad29720c6f2d8585b7930b1', 'assets/Figure2/P-C2-R1-TS_16H-shift/P-C2-R1-TS_16H-shift-DFT-Conf2.log': 'sha256:e61c6b20dbf29a1c50a7ce6f05f8fde5e9be20a1e6291c64f54c9298228442a4', 'assets/Figure2/P-C2-R1-TS_16H-shift/P-C2-R1-TS_16H-shift-DFT.log': 'sha256:ed04c9a7d7ad5ea2dc5580769c33abbf430a4956b09486222af011b989b96235', 'assets/Figure2/P-C2-R2-TS_14H-shift/P-C2-R2-TS_14H-shift-DFT.log': 'sha256:2da1a1418668286174f19c8edac1665e4438f6e7eba34ee4909ece6218552792', 'assets/Figure2/P-C2-R3-TS_17H-shift/P-C2-R3-TS_17H-shift-DFT-Conf2.log': 'sha256:0ce42495cff268a2ecd8ddba0a606532af2555812b07194cf8556baf298fb77c', 'assets/Figure2/P-C2-R3-TS_17H-shift/P-C2-R3-TS_17H-shift-DFT.log': 'sha256:901d4b1ac9b6c4d0f6364a792fa8d3f92037db54bacda9585d33ad6e329426e6', 'assets/Figure2/R1/R1-DFT-Conf2.log': 'sha256:237ef3743a5a1f0bf3dd504df6dd7d194c9c776dab0c2d44247050ceb8232295', 'assets/Figure2/R1/R1-DFT-Conf3.log': 'sha256:8a837e7bc6f707653a268d2a55c7bf99aca3d8e393692ccb105abf72e49e0250', 'assets/Figure2/R1/R1-DFT-Conf4.log': 'sha256:d71230932c45f7e05cfe470b9f83ddff4befe1e90c3369056e9f867a5b5e82a1', 'assets/Figure2/R1/R1-DFT-Conf5.log': 'sha256:d1969cecde26738afdc68829b39bd8876dbb5e83b22cc46ff60c5f966b912b9d', 'assets/Figure2/R1/R1-DFT.log': 'sha256:b2fa37a790ef259a57fd55cf4857f3fec2a53e1a7e05225a2967b0894155d751', 'assets/Figure2/R1-C7H8O5-O2add-RO2/R1-C7H8O5-TS-O2add-DFT-Conf2.log': 'sha256:fb5ac00d025fb8eae8d2cbeb9bf8181439bfcf52321182efc25898ef6368a1c9', 'assets/Figure2/R1-C7H8O5-O2add-RO2/R1-C7H8O5-TS-O2add-DFT-Conf3.log': 'sha256:b0eb9abd69ed35592369709927f7af97e04feb53cf6378293f80fd7c95884829', 'assets/Figure2/R1-C7H8O5-O2add-RO2/R1-C7H8O5-TS-O2add-DFT-Conf4.log': 'sha256:3a809dc7ddc594c8bc5751fbbed0a7acb4f1472b120c20cdc862a82398257221', 'assets/Figure2/R1-C7H8O5-O2add-RO2/R1-C7H8O5-TS-O2add-DFT-Conf5.log': 'sha256:eddeaad1fb7a5559dc8a4cc8a93e3cc68b7293ba31c331ceffb6a410e1b2ab26', 'assets/Figure2/R1-C7H8O5-O2add-RO2/R1-C7H8O5-TS-O2add-DFT-Conf6.log': 'sha256:562593798a0914eda39ac0a74c89b2a011c28fd6e07d971b48ba0d5f1f78404c', 'assets/Figure2/R1-C7H8O5-O2add-RO2/R1-C7H8O5-TS-O2add-DFT-Conf7.log': 'sha256:eeaa3f3ffe7efc9574d5733937a4f015e371dc1eb47e92ddfd9caa57feafac29', 'assets/Figure2/R1-C7H8O5-O2add-RO2/R1-C7H8O5-TS-O2add-DFT-Conf8.log': 'sha256:04fb8cbfbf7c72044bd654bc7b551fe04d5d94e64b0db29db479d83da7ab0f4f', 'assets/Figure2/R1-C7H8O5-O2add-RO2/R1-C7H8O5-TS-O2add-DFT-Conf9.log': 'sha256:f926c841405efeaf80174af89f6b2330a9e43f863ac52bd142d26516e894c998', 'assets/Figure2/R1-C7H8O5-O2add-RO2/R1-C7H8O5-TS-O2add-RO2-DFT.log': 'sha256:9d66fb6d4185505b11ca09492c171c14daaa14338ee5ae6585f74281d48d751c', 'assets/Figure2/R1-C7H8O5-TS-O2add/R1-C7H8O5-TS-O2add-DFT-Conf2.log': 'sha256:3ee5b560c247fbe328aff348a885353e68dde776ca963091d50d71d424cf4861', 'assets/Figure2/R1-C7H8O5-TS-O2add/R1-C7H8O5-TS-O2add-DFT-Conf3.log': 'sha256:025048147e240d4e8d6a281e5e3bb8b66e8b70801ecfee21b752ed62b06ed40b', 'assets/Figure2/R1-C7H8O5-TS-O2add/R1-C7H8O5-TS-O2add-DFT-Conf4.log': 'sha256:cccf85d5af2183e36afa5f0fc6c392d82978b93de7f63e4cefa391d485b4a82b', 'assets/Figure2/R1-C7H8O5-TS-O2add/R1-C7H8O5-TS-O2add-DFT-Conf5.log': 'sha256:46a7d5d906e3f63bd86020c7bc9ffeb065051b08c0f4d3c09ed52148d187d29a', 'assets/Figure2/R1-C7H8O5-TS-O2add/R1-C7H8O5-TS-O2add-DFT-Conf6.log': 'sha256:0de64739d860c36bb644f7575fa8d88e21f5fd22e0d3b67c2adfe177841ca49f', 'assets/Figure2/R1-C7H8O5-TS-O2add/R1-C7H8O5-TS-O2add-DFT-Conf7.log': 'sha256:c5027d29b277969bcc59106817a96f3b3fe35afd3788ef849ab10307215006f0', 'assets/Figure2/R1-C7H8O5-TS-O2add/R1-C7H8O5-TS-O2add-DFT-Conf8.log': 'sha256:6ddc5f770f3073065a11941e270dcb0749fabc618fe7c097d7aa2ac711e52252', 'assets/Figure2/R1-C7H8O5-TS-O2add/R1-C7H8O5-TS-O2add-DFT-Conf9.log': 'sha256:2d0cdc639fd268eefa4acd7762d58f9efa58db1abd83f333e4f38a094f02441c', 'assets/Figure2/R1-C7H8O5-TS-O2add/R1-C7H8O5-TS-O2add-DFT.log': 'sha256:02fbca0fdffda8caaadf5cfdff40e18b76564f46a2e0778aba4bfedd35c65500', 'assets/Figure2/R1-R1b-TS-O2add/R1-R1b-TS-O2add-DFT-Conf2.log': 'sha256:6034783bca6644feea2296482e7496ef07c0c858de569d5e53123404252d4b70', 'assets/Figure2/R1-R1b-TS-O2add/R1-R1b-TS-O2add-DFT-Conf3.log': 'sha256:ada6bce05e6856d01820f6b40849ee27eaa2bec66fdf51961571b8e0b573a6cf', 'assets/Figure2/R1-R1b-TS-O2add/R1-R1b-TS-O2add-DFT-Conf4.log': 'sha256:fbb72eb3fdade83f8f53b4624d025249cdeb356d7fc5b3ef6384373885679b31', 'assets/Figure2/R1-R1b-TS-O2add/R1-R1b-TS-O2add-DFT.log': 'sha256:4419c54cf08265c6544f808e8914d7352e049b37c33d4c35fd38631765b7f6e6', 'assets/Figure2/R1b-OOH-vinoxy/R1b-OOH-vinoxy-DFT.log': 'sha256:6bbb4c409041d0df2732b73e3d2b52d1cab6f430f8b40522cc168348fcb984e7', 'assets/Figure2/R1b-RO2/R1b-RO2-DFT-Conf2.log': 'sha256:a3ab7013d8c64e35eda4605afc1fc86f2478279d3321dca896e488a06e8ab4c3', 'assets/Figure2/R1b-RO2/R1b-RO2-DFT-Conf3.log': 'sha256:3457d3e3f1a8b93af7b18f922587f6d558c19a26d4456bbb9317e48f82e23fe2', 'assets/Figure2/R1b-RO2/R1b-RO2-DFT.log': 'sha256:7f61e2e1a2386d5e443b73a2b97802154e2aff6b2e370af779c72349cef9722f', 'assets/Figure2/R1b-RO2-R1b-OOH-TS_16H-shift/R1b-RO2-R1b-OOH-TS_16H-shift-DFT-Conf2.log': 'sha256:9a8cd71cbec351a053ce81c0dc41cf02594c53a39b5a14f9a5839cccbbca44a2', 'assets/Figure2/R1b-RO2-R1b-OOH-TS_16H-shift/R1b-RO2-R1b-OOH-TS_16H-shift-DFT.log': 'sha256:799bf4959918c47395956b3063374e9015de45d91c071edc8c140695a2eb830f', 'assets/Figure2/R2/R2-DFT-Conf1.log': 'sha256:7fb1e3ab57127f317472b6584529a4c88ec112ac799089c67e404ddcc57ef255', 'assets/Figure2/R2/R2-DFT-Conf2.log': 'sha256:683705985fcef07bf545568aede2ba9a7c66c60a9d19171c69a9c413345e4774', 'assets/Figure2/R2/R2-DFT-Conf3.log': 'sha256:ee75d4b810cfcb2432c8f96e88e5d0f1c9e73f55edc485a5473be5a3d6f0df0c', 'assets/Figure2/R2/R2-DFT-Conf4.log': 'sha256:6f923e0759c2e482c5c3a84cefb5f52524a620c62185c63cafb1953a687029bf', 'assets/Figure2/R2/R2-DFT-Conf5.log': 'sha256:1f1ca8cc53f6c96f950aca652f7c8ee424d6dc61346c63121f6b065470e9f120', 'assets/Figure2/R2/R2-DFT-Conf6.log': 'sha256:425fe9b67559b22b3a75be72ce708e9834c1ec3e5cdf04f6cca81e0096a24834', 'assets/Figure2/R2/R2-DFT.log': 'sha256:aa363a9eda543a959fb54ded251ce36d8751850cb1d009b1bb25ddf13a2be3d6', 'assets/Figure2/R2a-RO2/R2a-RO2-DFT-Conf2.log': 'sha256:2f9f5e966f541243c3a251d3a0446707b5d944ed6872bf84c98cd0bd97c446b1', 'assets/Figure2/R2a-RO2/R2a-RO2-DFT-Conf3.log': 'sha256:717a3fa6e8a9323c57f13cccd27bce4b06bd6b32959f855a6bc09bab58b64d42', 'assets/Figure2/R2a-RO2/R2a-RO2-DFT-Conf4.log': 'sha256:1e10e6cea168a2cefb8067defa2441ced03d02624c43d14c2afb775f02ab8da1', 'assets/Figure2/R2a-RO2/R2a-RO2-DFT-Conf5.log': 'sha256:e164fa11c2bed05776e356b0f6e5ba396cb5a787155c9766e996ab8ce72a845e', 'assets/Figure2/R2a-RO2/R2a-RO2-DFT-Conf6.log': 'sha256:0df6ef34f2fbaedee20fd1444e32f62d0827e0d200f20ffc47a8264cf88e0dc0', 'assets/Figure2/R2a-RO2/R2a-RO2-DFT-Conf7.log': 'sha256:f46a61f28e79c374eb5626d2100581b0192e035e2c93838a8958d10959d6f048', 'assets/Figure2/R2a-RO2/R2a-RO2-DFT-Conf8.log': 'sha256:a700b40364645b90eedeb6ecf4e0018c4ceb25846e308211967c4ef06247442b', 'assets/Figure2/R2a-RO2/R2a-RO2-DFT-Conf9.log': 'sha256:feb6f67e21884c5a518ce3c1b115a9735d17a947e920bd96df410afec6afc47f', 'assets/Figure2/R2a-RO2/R2a-RO2-DFT.log': 'sha256:057582d1a86d3f29499443dd919555109da8f856978163f74bae6a75607b83bd', 'assets/Figure2/R2a-RO2-R2b-RO2-TS_16H-shift/R2a-RO2-R2b-RO2-TS_16H-shift-DFT.log': 'sha256:25bc836a978b420b80141a1c14c3b1ed464213a17feff70af906169d0129a3a9', "assets/Figure2/R2b-OOH-R'1/R2b-OOH-R1-DFT.log": 'sha256:d21b483494297a843ccfa30a6c168d3c893907c0cd601025a7164a3631b2e0bc', "assets/Figure2/R2b-OOH-R'2O2-R2b-OOH-vinoxy-TS_16H-shift/IRC/forward-b3lyp-freq.log": 'sha256:3f0222d1a9583d7e0d6c9371ec478e3fb3202d70933add9f72b169abcf03bccd', "assets/Figure2/R2b-OOH-R'2O2-R2b-OOH-vinoxy-TS_16H-shift/IRC/reverse-b3lyp-freq.log": 'sha256:685bb9dde5498d2c91009df8569d5d71a191466ef4173e29fe4479cf7fb75dc1', "assets/Figure2/R2b-OOH-R'2O2-R2b-OOH-vinoxy-TS_16H-shift/aldO9-OH-Hshift-TS-CONF-M0009-copt-TS-opt.log": 'sha256:c9942b54ec71a3c01a6dc68710ecf907314529671df3639f7bf6e574d88c0fc9', "assets/Figure2/R2b-OOH-R'2O2-R2b-OOH-vinoxy-TS_16H-shift/aldO9-OH-Hshift-TS-CONF-M0016-copt-TS-opt.log": 'sha256:77f134605b32c25a33674d898e36092a321a6f3947da06c8950756d6e805de93', "assets/Figure2/R2b-OOH-R'2O2-R2b-OOH-vinoxy-TS_16H-shift/aldO9-OH-Hshift-TS-CONF-M0018-copt-TS-opt.log": 'sha256:6b4fa3b114a1738507459b5e22a291b3cac568eadb4777313818ff5fb4881c6c', 'assets/Figure2/R2b-RO2/R2b-RO2-DFT-Conf10.log': 'sha256:39e3eed3c434b4eb4aed489b5cee3dc60ec88d35fcad7acffa96eff249ebffea', 'assets/Figure2/R2b-RO2/R2b-RO2-DFT-Conf2.log': 'sha256:8e50e54963092b8e4920f203cb6676384a8d15df8c34af0ecaffd039e518624e', 'assets/Figure2/R2b-RO2/R2b-RO2-DFT-Conf3.log': 'sha256:4a66c85e470356940af31a9555da7666bbfcbc400a59f70e76cc0cb0a28855f3', 'assets/Figure2/R2b-RO2/R2b-RO2-DFT-Conf4.log': 'sha256:dfc7b749d1dee10e93e082cd4619fd0c24b0ba58893246030455d6357fb757f7', 'assets/Figure2/R2b-RO2/R2b-RO2-DFT-Conf5.log': 'sha256:53e9996b7bdab3891c4c7064ed908cad3701c47b89c2100513edd1bcb8754902', 'assets/Figure2/R2b-RO2/R2b-RO2-DFT-Conf6.log': 'sha256:70e704bc0bf277d21b9ee53f1f41b47298e734e4cadb74a9bf273633148ebf41', 'assets/Figure2/R2b-RO2/R2b-RO2-DFT-Conf7.log': 'sha256:a3e971449cb0933d78fe9031e54b3362c1305e7d304c0cf359ab88778c00427a', 'assets/Figure2/R2b-RO2/R2b-RO2-DFT-Conf8.log': 'sha256:1444cb5e68bc81d988a7e9e65fd639c0299e416edb57c053d6b994e68d4192a7', 'assets/Figure2/R2b-RO2/R2b-RO2-DFT-Conf9.log': 'sha256:ae2b01afda6fcb0cdd8f4830026d9a879cb3d0fee342f7d7b2a02fa1bffe3f31', 'assets/Figure2/R2b-RO2/R2b-RO2-DFT.log': 'sha256:685ab308cd023c9ab6529c8a78c6b6c4fff4da852d0a1b5977e7002ab4d847c5', 'assets/Figure2/R2b-RO2-R2b-OOH-R1-TS_16H-shift/R2b-RO2-R2b-OOH-R1-TS_16H-shift-DFT-Conf2.log': 'sha256:856f5f8eff140198dc4aa033ebd7ce20c1f902219a5354e857e29ddc511f51b5', 'assets/Figure2/R2b-RO2-R2b-OOH-R1-TS_16H-shift/R2b-RO2-R2b-OOH-R1-TS_16H-shift-DFT.log': 'sha256:da4437a68b871bc69091707e016076637b93c8a63c4e759505426536a952cfae', 'assets/Figure2/R3/R3-DFT-Conf2.log': 'sha256:bb48ae30783ceaf8b4dfb1f3edc2937c26d6e5a90f9c2a3a00a6f0ca07dbdc2c', 'assets/Figure2/R3/R3-DFT-Conf3.log': 'sha256:a49aefd90951f0b6357848eda80d50198e7fd3a937e235b9b5fc70a188c5d773', 'assets/Figure2/R3/R3-DFT-Conf4.log': 'sha256:210b29b55ec9e06aa8febbcbe5a99cf09e5760806d90301c210dcf263322c81e', 'assets/Figure2/R3/R3-DFT.log': 'sha256:e30e62e74f23fc7bed1344b12e29df23d01275cb422c09fe01fb51138146d311', "assets/Figure2/R3-EPO-R'O2-R3-Epo-OOH-TS_15H-shift/R3-Epo-RO2-R3-Epo-OOH-TS_15H-shift-DFT-Conf2.log": 'sha256:7daa647b7713766636a5ddbc305176e0e72acaac85fc64571eb77a658d528550', "assets/Figure2/R3-EPO-R'O2-R3-Epo-OOH-TS_15H-shift/R3-Epo-RO2-R3-Epo-OOH-TS_15H-shift-DFT.log": 'sha256:a32d4daf5bfb436605370c5f3b56d684516811f1309a05b0f2d159cfd5849d77', "assets/Figure2/R3-Epo-R'/R3-Epo-R-DFT.log": 'sha256:8bbb780b0db79bd308ac162cb31738b4cdb90d997961e3cd98a3eda80d9ec062', "assets/Figure2/R3-Epo-R'O2/R3-Epo-RO2-DFT-Conf2.log": 'sha256:75c54077be6f09f037b4096abd1aa0e3e4de24760820185a84468b5f9d28497d', "assets/Figure2/R3-Epo-R'O2/R3-Epo-RO2-DFT-Conf3.log": 'sha256:bb05f0766af927b640e326a4cb114b3b9bba717b21a336eadee7d7e504f5ac5c', "assets/Figure2/R3-Epo-R'O2/R3-Epo-RO2-DFT-Conf4.log": 'sha256:27a61e9407662885b444e19e780e801969cc79e9c59590408420945070169b13', "assets/Figure2/R3-Epo-R'O2/R3-Epo-RO2-DFT-Conf5.log": 'sha256:cb59ea2f4f3ffedf62ee0bb4c8fa391d66921e946ba6e9c1039f69846c652738', "assets/Figure2/R3-Epo-R'O2/R3-Epo-RO2-DFT.log": 'sha256:745894c2ebeddbf29e318a73eb0883542983225b4677cc4aa575224a9fc221b5', "assets/Figure2/R3-R3-Epo-R'-TS_epoxide/R3-R3-Epo-R-TS_epoxide-DFT-Conf10.log": 'sha256:e00f639273ef6f14adf1cd13752a2d1712e802be908095e6ecc9aa561b325657', "assets/Figure2/R3-R3-Epo-R'-TS_epoxide/R3-R3-Epo-R-TS_epoxide-DFT-Conf2.log": 'sha256:1ce6dfc02d98b56c73c19d0a1bb6dbffaa31b157ca7f4d45a0e9a0de2655e356', "assets/Figure2/R3-R3-Epo-R'-TS_epoxide/R3-R3-Epo-R-TS_epoxide-DFT-Conf3.log": 'sha256:3a6843c67a41a82146cbae822519e2eea23958e4273b967cd3e89abdbb2d249b', "assets/Figure2/R3-R3-Epo-R'-TS_epoxide/R3-R3-Epo-R-TS_epoxide-DFT-Conf4.log": 'sha256:85ce0281a31e4bbff95e2971b2e07d42b5d652b1757a25f1dd61c4d0eb9c4f56', "assets/Figure2/R3-R3-Epo-R'-TS_epoxide/R3-R3-Epo-R-TS_epoxide-DFT-Conf5.log": 'sha256:05498176242cefe72a4f47817907623028c44806c19400e0b719911b327cb361', "assets/Figure2/R3-R3-Epo-R'-TS_epoxide/R3-R3-Epo-R-TS_epoxide-DFT-Conf6.log": 'sha256:cac00600769167f9562d9b058d703dbb3877e561d5edd57b672362396c2f40d5', "assets/Figure2/R3-R3-Epo-R'-TS_epoxide/R3-R3-Epo-R-TS_epoxide-DFT-Conf7.log": 'sha256:b9a9266acc9573025ff302f870de7e61e95786f51be1e39c73b5679848893d56', "assets/Figure2/R3-R3-Epo-R'-TS_epoxide/R3-R3-Epo-R-TS_epoxide-DFT-Conf8.log": 'sha256:e210911befeab5841170af82cff566c7aa392208fce3017b9339ec66536fcdd7', "assets/Figure2/R3-R3-Epo-R'-TS_epoxide/R3-R3-Epo-R-TS_epoxide-DFT-Conf9.log": 'sha256:b037425bb5f0cd583aa04f36431243091e0765087aae3f62292e672c373f10c6', "assets/Figure2/R3-R3-Epo-R'-TS_epoxide/R3-R3-Epo-R-TS_epoxide-DFT.log": 'sha256:56a96979761de4b047e79e5cadbb0b17df60f605241307117b68456aa343c710', 'assets/Figure4/Benzene/Benzene-BPR-DFT.log': 'sha256:3f628ddd83e36d8c7a5d04a41f99d6f7ac7f07245be212d139e0b0fb48b30df7', 'assets/Figure4/Benzene/Benzene-TS-C1-DFT.log': 'sha256:7676a27dd8cd2c9a6e8994e34879e9bab6ccf9b79434b99b4fe7a3332825a470', 'assets/Figure4/Benzene/Benzene-TS-C2-DFT.log': 'sha256:72981830e8541a0bf7bda1217be0e1c59f5ee6e287a5b90fc6530f7fcc52b491', 'assets/Figure4/E-Benzene/E-Benzene-iBPR-DFT.log': 'sha256:42eaba0a8062aa7b3d3da689f1b6227e520789bf300fadefb9fe5c89e0f26a0c', 'assets/Figure4/E-Benzene/E-Benzene-iBPR-TS-C1-DFT.log': 'sha256:597318118f1d2dd56d13e8bb01355923fe56c66f8c36d8b2df542b26b16fd50d', 'assets/Figure4/E-Benzene/E-Benzene-iBPR-TS-C2-DFT.log': 'sha256:fc89b9ea6f9725c786b6c90141dd4f0e4d7a151e051284db7a843e16c5ddeecd', 'assets/Figure4/E-Benzene/E-Benzene-oBPR-DFT.log': 'sha256:088ad220006b190e2464a65f87abc1973a1ec58a4fae2b38106f5adaeb38a5c7', 'assets/Figure4/E-Benzene/E-Benzene-oBPR-TS-C1-DFT.log': 'sha256:0d88a1847f6786332a7b1e75af55617acdc840b36aa35264c074e956347f1902', 'assets/Figure4/E-Benzene/E-Benzene-oBPR-TS-C2-DFT.log': 'sha256:850459a7e9bcdef5a5b829f08a895d79f1899ef222464feae30ec56c322f9364', 'assets/Figure4/E-Benzene/E-Benzene-pBPR-DFT.log': 'sha256:d1379f115fb3edc0be4ac1c2f28ffcdd7a3bc2f180c1b73a416a06351d3a6d6f', 'assets/Figure4/E-Benzene/E-Benzene-pBPR-TS-C1-DFT.log': 'sha256:b452d3be9e90d266fdc3bc077a2cc9a3700ec614a37160532769cbe33b9ea58d', 'assets/Figure4/E-Benzene/E-Benzene-pBPR-TS-C2-DFT.log': 'sha256:a1af156f54607b61e43bc3809d2548084d8082fff939d5f34a7f220188598c31', 'assets/Figure4/I-Benzene/I-Benzene-iBPR-DFT.log': 'sha256:90c56c046d6146ccd5883ebe57d6ea9b90233a207ecd44ac6599e064e79b9cc2', 'assets/Figure4/I-Benzene/I-Benzene-iBPR-TS-C1-DFT.log': 'sha256:de037d5b4150541b77397f62d06d1e8065d748a1f1d6e991005a3555f0d0aef9', 'assets/Figure4/I-Benzene/I-Benzene-iBPR-TS-C2-DFT.log': 'sha256:5d861955e22790b80f045c36b28cf79153ad45f8b783bf0b70723d0c4cd84095', 'assets/Figure4/M-Xylene/Meta-Xylene-iBPR-DFT.log': 'sha256:250649ae13f2bddd8743fd1b1bec0e1d9c89e67951adbb6ff318a3b6a2f65e5b', 'assets/Figure4/M-Xylene/Meta-Xylene-iBPR-TS-C1-DFT.log': 'sha256:1e411a71169a7491b63d1f966147565710e9a1cead3228d8f970f2ea4b7f8c4d', 'assets/Figure4/M-Xylene/Meta-Xylene-iBPR-TS-C2-DFT.log': 'sha256:10e0a0df5b82dad9eab0b9ede1aa335819ae5886592a35fd50965970e7cb5a23', 'assets/Figure4/M-Xylene/Meta-Xylene-mBPR-DFT.log': 'sha256:38ddcd3850cae20e716fb678c8497a2f1e1fd16650dcae6c5016cabda4b0ea06', 'assets/Figure4/M-Xylene/Meta-Xylene-mBPR-TS-C1-DFT.log': 'sha256:8cf5d43b0482d73f7be94841909f6a5a3f1a1c9c4035325157759e24991f8c3f', 'assets/Figure4/M-Xylene/Meta-Xylene-mBPR-TS-C2-DFT.log': 'sha256:8932122bb68b0057523010731aaac57b6a05121ba53afea206f136f91e1a89f4', 'assets/Figure4/M-Xylene/Meta-Xylene-oBPR-DFT.log': 'sha256:e265b7a00162bc3d5caabf82124b91af5e280f7f5a89eb375d8170cf72cf449e', 'assets/Figure4/M-Xylene/Meta-Xylene-oBPR-TS-C1-DFT.log': 'sha256:d4e69265cfff55dd30a1f75accb734c34cb23a9cf16fed25fa70975c2f9d3c2c', 'assets/Figure4/M-Xylene/Meta-Xylene-pBPR-DFT.log': 'sha256:70a0a863915219b6f097b8be61f50ce0b6f86445a5e49babfa20455afe049b9a', 'assets/Figure4/M-Xylene/Meta-Xylene-pBPR-TS-C1-DFT.log': 'sha256:29c75f55277d5c4f04b153cc0d1041f2e06de926ddb865a55ca0e4363a56d63c', 'assets/Figure4/M-Xylene/Meta-Xylene-pBPR-TS-C2-DFT.log': 'sha256:42048a76ffe972f0b2327c3820f5ab0962f8233ba31bff3c37b15fbf3af15cbf', 'assets/Figure4/O-Xylene/Ortho-xylene-iBPR-DFT.log': 'sha256:132c0dbd0f514bd188d4c93fb9bf136a6b0cc8960dd58db6ac31f9285ee58545', 'assets/Figure4/O-Xylene/Ortho-xylene-iBPR-TS-C1-DFT.log': 'sha256:c2045df9ebb6afcd64a7ce74f5257aa70bd1263e941aa66a18b354712e93dabb', 'assets/Figure4/O-Xylene/Ortho-xylene-iBPR-TS-C2-DFT.log': 'sha256:2c7303250ee75acde1e657a1fb9e534f243dfa6e3057f25632f32d1c6e6e8182', 'assets/Figure4/P-Xylene/Para-Xylene-iBPR-DFT.log': 'sha256:231b49abc7253f026ef3be2ce2f93fe9de7b10d88c4bcfa304b89e48343b5faf', 'assets/Figure4/P-Xylene/Para-Xylene-iBPR-TS-C1-DFT.log': 'sha256:3d646fb5c139d845fd4580b0f507e2bd90359070ddef5263b56ab6c3481dee9e', 'assets/Figure4/P-Xylene/Para-Xylene-iBPR-TS-C2-DFT.log': 'sha256:5ea69af2c0e60647ebafdcec0b659d28e03f596e363b92a4c8a69343d905fffc', 'assets/Figure4/P-Xylene/Para-Xylene-oBPR-DFT.log': 'sha256:7ad06e77ba22aafd42096b0f9224ec1ce62c463a7a469261eb4f565954bccd46', 'assets/Figure4/P-Xylene/Para-Xylene-oBPR-TS-C1-DFT.log': 'sha256:3351ade3f986506b1ffae6872d703e0f12e6e32ecdb61b010d92874a00e4f7ba', 'assets/Figure4/Toluene/Toluene-OBPR-TS-C1-DFT.log': 'sha256:903f7f05013d56bf35e26f7e7d39a9566209256feb094f453614cc274eae992f', 'assets/Figure4/Toluene/Toluene-OBPR-TS-C2-DFT.log': 'sha256:6ebaa2901673c572df42cd0f1e2106b5c2c2e6ad15dac1bcaca025b47635e5d3', 'assets/Figure4/Toluene/Toluene-iBPR-DFT.log': 'sha256:d2d7720643c371c07c3e34ea673ac6e70f7e4d610577241e7a7a87e368d168f1', 'assets/Figure4/Toluene/Toluene-iBPR-TS-C1-DFT.log': 'sha256:f02930ff0889df3b786d4313edb5a2202c993737b5bd32eda272cbeb5e1381e5', 'assets/Figure4/Toluene/Toluene-iBPR-TS-C2-DFT.log': 'sha256:b598d6a3f39fc3e01b3057e1410d77fe8e0ade8032c8886b2a6480806496fc7f', 'assets/Figure4/Toluene/Toluene-mBPR-DFT.log': 'sha256:af3d21a106f4c86df641c7fc9be2929d9be2107d6e487139f7c32540c2627f82', 'assets/Figure4/Toluene/Toluene-mBPR-TS-C1-DFT.log': 'sha256:60abdbfeaafe36719cc622be41b9c9d5016e6307043a0351f23d8a3edd20c35d', 'assets/Figure4/Toluene/Toluene-mBPR-TS-C2-DFT.log': 'sha256:345df740e395994c2740437fd71d4e5b3eb1495793a3b294fe0af6d4256a8a26', 'assets/Figure4/Toluene/Toluene-oBPR-DFT.log': 'sha256:63c21815965a81a1a729daa0a5620b11eabefbc0f77fa9ab05722df9b300da7d', 'assets/Figure4/Toluene/Toluene-pBPR-DFT.log': 'sha256:7dfbb08a005bd851d4d47547670e7da42a3a9001906cbc2d5f303c1af06901ee', 'assets/Figure4/Toluene/Toluene-pBPR-TS-C1-DFT.log': 'sha256:a9044e613a370c29694f51d98de4e9a23e6d4abe103c8429d8c192bbab7e20f1', 'assets/Figure4/Toluene/Toluene-pBPR-TS-C2-DFT.log': 'sha256:76482fa4372640c6f61a7fccebd6f011427ebffac16c89f7f1295423c010f48f', 'assets/RONO2/Benzene/B-RO-DFT.log': 'sha256:70f54a3cc5967f588918b8a91da038349f889fef8643fc96af178dfd9cd96984', 'assets/RONO2/Benzene/B-RONO2-DFT.log': 'sha256:a785f20a8938400484a1f4e41bd3dcc1113925dd149467c51e6357777eed1b39', 'assets/RONO2/Benzene/Benzene-BPR-DFT.log': 'sha256:3f628ddd83e36d8c7a5d04a41f99d6f7ac7f07245be212d139e0b0fb48b30df7', 'assets/RONO2/Benzene/RB-RO-DFT.log': 'sha256:2392944b5b4ad419a07f97deb14b98998ee01e0f68f6574e255426b5652051da', 'assets/RONO2/Benzene/RB-RONO2-DFT.log': 'sha256:6b6ddfe2f8c65fad160354865e10b5ec6dd9863024a963f033e13499e9251d15', 'assets/RONO2/Benzene/TS-C1-DFT.log': 'sha256:26656d7290c74293d127663528f2cd6bd256298f93f19c261f3f3d7e29da2a3c', 'assets/RONO2/Benzene/TS-C2-DFT.log': 'sha256:fffdd74fee2c7d6f65e09cdbaca55b128dc7c0396718a68f55616101b1eddf54', 'assets/RONO2/NOx/NO-DFT.log': 'sha256:1bcabf5b58e93e4cf870af69b39bd28b4a56c855617f7ba627adc5548f89b88c', 'assets/RONO2/NOx/NO2-DFT.log': 'sha256:52ed9a1997cdb3190ff62709e3cd12b4b65ab142e985dc908647a1b7d9637903', 'assets/RONO2/Toluene/Ipso/B-RO-DFT.log': 'sha256:c9871b2b76a1938b1422929311811b2c97a06701ac65255ed91d4c1ce849cd44', 'assets/RONO2/Toluene/Ipso/B-RONO2-DFT.log': 'sha256:4764efaf7b643de0f22cc7fc37efb466dc604271eeeab97a80846376e3e25766', 'assets/RONO2/Toluene/Ipso/RB-RO-DFT.log': 'sha256:bc14856e2090b9240b66b3df0efbfb2b29159509da176980109b67c2a3fb8af8', 'assets/RONO2/Toluene/Ipso/RB-RONO2-DFT.log': 'sha256:1149527c60a2b93a2759dd241d460752164a29ccfdbcdfa05596aec783e7c3ef', 'assets/RONO2/Toluene/Ipso/TS-DFT.log': 'sha256:63e8dc918abca92dc9eeb8bd8f10375c2ca5f1792c3633470bcd53073a258422', 'assets/RONO2/Toluene/Ipso/Toluene-iBPR-DFT.log': 'sha256:d2d7720643c371c07c3e34ea673ac6e70f7e4d610577241e7a7a87e368d168f1', 'assets/RONO2/Toluene/Meta/B-RO-DFT.log': 'sha256:83ee7b2e96e5e2d2597c310686fb06335b0d5018b6e74d3c54ac5e9d22ac4044', 'assets/RONO2/Toluene/Meta/B-RONO2-DFT.log': 'sha256:c26f5edcf6e190d077387b5f38d45cd67d69df90e7dfbf5b90281153af3b71e1', 'assets/RONO2/Toluene/Meta/RB-C1-RO-DFT.log': 'sha256:83ee7b2e96e5e2d2597c310686fb06335b0d5018b6e74d3c54ac5e9d22ac4044', 'assets/RONO2/Toluene/Meta/RB-C1-RONO2-DFT.log': 'sha256:41a80730922345d86a458e8ec384af2817749d27658113b4316c9cdcfc1a824f', 'assets/RONO2/Toluene/Meta/RB-C2-RO-DFT.log': 'sha256:0ad60b918b21a46e4793cdd183c78bdb7724fcdea0162c6183512982d4e26e14', 'assets/RONO2/Toluene/Meta/RB-C2-RONO2-DFT.log': 'sha256:7e2a36220db0d7be6d5a4549d1b4bf88762784ca5d75b2b07052077e1634cacc', 'assets/RONO2/Toluene/Meta/TS-C1-DFT.log': 'sha256:bbb978c4f1db7f410bf882b5e0171102ca1b30d31281f1be21cec40d20241da7', 'assets/RONO2/Toluene/Meta/TS-C2-DFT.log': 'sha256:8e450345c25e7a6e4aa842a5736a6581aac715ef1395b46c061b9cc47af3249d', 'assets/RONO2/Toluene/Meta/Toluene-mBPR-DFT.log': 'sha256:af3d21a106f4c86df641c7fc9be2929d9be2107d6e487139f7c32540c2627f82', 'assets/RONO2/Toluene/Ortho/B-RO-DFT.log': 'sha256:1fd03c3f5d630533fa59ae6364f2dd005980f3e9e3662bef2e23eaeae39b59d0', 'assets/RONO2/Toluene/Ortho/B-RONO2-DFT.log': 'sha256:f526b2e43135dc8d7fe2414052211741b7cf52a64af22af50191b3f4787a07e2', 'assets/RONO2/Toluene/Ortho/RB-C1-RO-DFT.log': 'sha256:1ff1f2e2553fe113799144e2ca46694c8a60d1ed0e3d0afd17c0f115a1238fb8', 'assets/RONO2/Toluene/Ortho/RB-C1-RONO2-DFT.log': 'sha256:0fb2b86b236b64b614f5fff86826775a46dd3f006b828653a5e9d88c19e96d04', 'assets/RONO2/Toluene/Ortho/RB-C2-RO-DFT.log': 'sha256:095cafaa63199a6eb2492a3a02e9a479e03a2f5b34426cc7bd3b0c761d89d506', 'assets/RONO2/Toluene/Ortho/RB-C2-RONO2-DFT.log': 'sha256:980cd5da88471427c0471ce3b6bb9bd8f8d438224a9346226ebc284ccb5e4f0f', 'assets/RONO2/Toluene/Ortho/TS-C1-DFT.log': 'sha256:3edb1314324678e5f61a8f58b0e65842f320acc81981603005e7c948b7462df0', 'assets/RONO2/Toluene/Ortho/TS-C2-DFT.log': 'sha256:ec9f97c261b22aa70f3ed523eae914418a0bd3fc5fce6666d29523387099d437', 'assets/RONO2/Toluene/Ortho/Toluene-oBPR-DFT.log': 'sha256:63c21815965a81a1a729daa0a5620b11eabefbc0f77fa9ab05722df9b300da7d', 'assets/RONO2/Toluene/Para/B-RO-DFT.log': 'sha256:919819eb39f6415e31a1c0a5c5ec8553f8b1427c7a8e55de6c7454296ca100e7', 'assets/RONO2/Toluene/Para/B-RONO2-DFT.log': 'sha256:b652920d8a54aa2b4f858b398ecac21d355a6b950e865f308f76c8463d562df3', 'assets/RONO2/Toluene/Para/RB-C1-RO-DFT.log': 'sha256:4e96e2a4e76b1d951707ef837cac1b1f20710b858d2af2ca357564ce46cbfab0', 'assets/RONO2/Toluene/Para/RB-C1-RONO2-DFT.log': 'sha256:c80cf9faecc7add6249537681f305272bd3733d955c5b17e34ac8e08287f7d28', 'assets/RONO2/Toluene/Para/RB-C2-RO-DFT.log': 'sha256:bae83439b5fe591892ff2c99ffd06386215283038529951eb0eb5a4fad7719cb', 'assets/RONO2/Toluene/Para/RB-C2-RONO2-DFT.log': 'sha256:7061f46046d5c63c415c03644be8a3f1e8b1ffbb8815d8e642189e5015cf3c31', 'assets/RONO2/Toluene/Para/TS-C1-DFT.log': 'sha256:f688d9e90c25d62a9c6f9f1f92f87c9f4f6a522f2a96c432d4bb4c6679fd1a19', 'assets/RONO2/Toluene/Para/TS-C2-DFT.log': 'sha256:614f0d12a569194198d64448e173b64ec3179371132285b1c3dbe48148109052', 'assets/RONO2/Toluene/Para/Toluene-pBPR-DFT.log': 'sha256:7dfbb08a005bd851d4d47547670e7da42a3a9001906cbc2d5f303c1af06901ee', 'assets/Toluene-iBPR-rearrangment/P-C1-DFT.log': 'sha256:6c129624447dbab6e34f6195cb32a2aa8c04658f08419510113c8d8f8380f2f0', 'assets/Toluene-iBPR-rearrangment/P-C2-DFT.log': 'sha256:249341d49148b71394d84ff7b8f03daf17168c7d2ad29720c6f2d8585b7930b1', 'assets/Toluene-iBPR-rearrangment/Toluene-iBPR-DFT.log': 'sha256:d2d7720643c371c07c3e34ea673ac6e70f7e4d610577241e7a7a87e368d168f1', 'assets/Toluene-iBPR-rearrangment/Toluene-iBPR-TS-C1-DFT.log': 'sha256:f02930ff0889df3b786d4313edb5a2202c993737b5bd32eda272cbeb5e1381e5', 'assets/Toluene-iBPR-rearrangment/Toluene-iBPR-TS-C2-DFT.log': 'sha256:b598d6a3f39fc3e01b3057e1410d77fe8e0ade8032c8886b2a6480806496fc7f', 'assets/Figure4/Toluene/Toluene-iBPR-F12.out': 'sha256:39fb1698aec8630e572a979d929e5ce11817a639930b1ff7641cfa61f064fa6e', 'assets/Figure4/Toluene/Toluene-iBPR-TS-C1-F12.out': 'sha256:9554d77f3303690a7316f588849e8bc9dcf2ab85c82d89240957cc2daac08eb1', 'assets/Figure4/Toluene/Toluene-iBPR-TS-C2-F12.out': 'sha256:4d2ff3a288cc3da670f36c6085d94875c80d64259b1e695dcbf5975ea3f99777', 'assets/Figure4/Toluene/Toluene-mBPR-F12.out': 'sha256:24c96a9437508b949334fd4f9daa6dce060c4b6307ae05b39c9021e102b86dd8', 'assets/Figure4/Toluene/Toluene-mBPR-TS-C1-F12.out': 'sha256:2f8a564d9fec861184ffda2f0f571a96bb36637d902bb639c6808b59337cb2a2', 'assets/Figure4/Toluene/Toluene-mBPR-TS-C2-F12.out': 'sha256:80e3f45c0898ec564ac593c05774cb70a8fb77ba6a9ae230c53adb80cbe18de2', 'assets/Figure4/Toluene/Toluene-pBPR-F12.out': 'sha256:69ac2cf015c4f7655812d4c187576e227de35f420b4ae5c05555dd1285e9e1de', 'assets/Figure4/Toluene/Toluene-pBPR-TS-C1-F12.out': 'sha256:d8f3f542894885418de56d3ddb5e2e9a56d896b903efe73fd3fa2404ec31fe43', 'assets/Figure4/Toluene/Toluene-pBPR-TS-C2-F12.out': 'sha256:bd365a45fd9a70d093f425e0913e324266b28be7c09b8f764a2ba355dcfb1428', 'assets/Figure4/Toluene/Toluene-OBPR-F12.out': 'sha256:681e8eb40ed8449dc589a38528ebe67701293f9b7b183f026ad0e682b5989c09', 'assets/Figure4/Toluene/Toluene-OBPR-TS-C1-F12.out': 'sha256:62e78275d9dd9d6dc36faa3dbbb89e58410ddf37ebecffb1d12b7e90833ce9d4', 'assets/Figure4/Toluene/Toluene-OBPR-TS-C2-F12.out': 'sha256:cbda374302d5d75ff057363e6b238058b558c2cdfa69b6a60dbb915a719b6eaf'}
PINNED_CASE_ID = 'case-02-transition-state-validation-conformers'


class CandidateFault(Exception):
    pass


class EnvironmentFault(Exception):
    pass


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return "sha256:" + h.hexdigest()


def rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames
            if not fields or len(fields) != len(set(fields)):
                raise CandidateFault(f"missing or duplicate CSV header: {path.name}")
            data = list(reader)
            if any(None in r or any(v is None for v in r.values()) for r in data):
                raise CandidateFault(f"inconsistent CSV field count: {path.name}")
            return [{k: v.strip() for k, v in r.items()} for r in data]
    except (OSError, UnicodeError, csv.Error) as e:
        raise CandidateFault(f"cannot read {path.name}: {e}") from e


def json_obj(path: Path) -> object:
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result: raise CandidateFault(f"duplicate JSON field: {k}")
            result[k] = v
        return result
    def finite_tree(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise CandidateFault("non-finite JSON number")
        if isinstance(value, dict):
            for x in value.values(): finite_tree(x)
        if isinstance(value, list):
            for x in value: finite_tree(x)
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique)
        finite_tree(value)
        return value
    except (OSError, UnicodeError, ValueError) as e:
        raise CandidateFault(f"cannot read {path.name}: {e}") from e


def text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").lower()
    except (OSError, UnicodeError) as e:
        raise CandidateFault(f"cannot read {path.name}: {e}") from e


def num(row: dict, key: str) -> float:
    try:
        if isinstance(row[key], bool): raise ValueError("boolean is not a number")
        x = float(row[key])
        if not math.isfinite(x): raise ValueError("not finite")
        return x
    except (KeyError, TypeError, ValueError, OverflowError) as e:
        raise CandidateFault(f"invalid numeric field {key}: {e}") from e


def near(a: float, b: float, tol: float, *, rel: bool = False) -> bool:
    return (not isinstance(a, bool) and not isinstance(b, bool) and math.isfinite(a) and
            math.isfinite(b) and abs(a-b) <= (tol*max(abs(b),1e-300) if rel else tol))


def regular_file(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
        current = root
        if root.is_symlink(): return False
        for part in parts:
            current = current / part
            if current.is_symlink(): return False
        return path.is_file() and root.resolve() in path.resolve().parents
    except (OSError, ValueError): return False

def public_asset(app: Path, value: str) -> Path:
    root = app / "assets"
    rel = Path(normalized_path(value))
    if len(rel.parts) == 1:
        matches = list(root.rglob(rel.name))
        if len(matches) != 1: raise CandidateFault("ambiguous/missing asset basename: "+rel.name)
        path = matches[0]
    else: path = root / rel
    if not regular_file(path, root): raise CandidateFault("asset is not a regular public file: "+str(value))
    return path

def submitted_path_matches(app: Path, value: str, expected: Path) -> bool:
    try:
        rel=Path(normalized_path(value))
        # In a field with a separately established species/site/channel source,
        # that scientific context disambiguates an exact expected basename.
        if len(rel.parts)==1:
            return rel.name==expected.name and regular_file(expected,app/"assets")
        return public_asset(app, value).resolve() == expected.resolve()
    except CandidateFault: return False

def level_name(value: str) -> str:
    name = value.lower().replace(" ", "").replace("ω", "w").replace("6-31+g*", "6-31+g(d)")
    name = re.sub(r"wb97x-?d", "wb97xd", name)
    # Gaussian route prefixes U/R describe the wavefunction, not a different
    # functional/basis; the native route is verified independently per row.
    return re.sub(r"^[ur](?=w?b97xd|b3lyp)", "", name)

def disposition(value) -> bool:
    v = str(value).strip().lower()
    if v in {"true", "yes", "1", "reconciled"}: return True
    if v in {"false", "no", "0", "unreconciled"}: return False
    raise CandidateFault("unknown Boolean disposition: "+str(value))

def number_in_prose(value: str, target: float, tol: float) -> bool:
    return any(near(float(x),target,tol) for x in re.findall(r"(?<![\w.])[-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?", value))

def missing_native_reason(value: str) -> bool:
    value = value.lower()
    return ("native" in value or "原生" in value) and any(x in value for x in ("no ","not ","missing","absent","未存储","未提供","不存在","缺失","并非","不是"))

def identical_reason(value: str) -> bool:
    return any(x in value.lower() for x in ("identical","byte-identical","相同","一致"))

def formula_value(formula: str, names: dict[str, float]) -> float:
    """Evaluate arithmetic only: no eval, imports, attributes, or arbitrary calls."""
    import ast
    expr = formula.split("=",1)[-1].strip().lower().replace("^","**").replace("math.exp", "exp").replace("math.log", "log")
    expr = expr.replace("[", "(").replace("]", ")")
    if len(expr)>500: raise CandidateFault("formula too long")
    try: tree=ast.parse(expr,mode="eval")
    except SyntaxError as e: raise CandidateFault("invalid formula syntax") from e
    if len(list(ast.walk(tree)))>80: raise CandidateFault("formula too complex")
    def visit(node):
        if isinstance(node,ast.Expression): return visit(node.body)
        if isinstance(node,ast.Constant) and type(node.value) in (int,float): return float(node.value)
        if isinstance(node,ast.Name) and node.id in names: return names[node.id]
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.USub,ast.UAdd)):
            v=visit(node.operand);return -v if isinstance(node.op,ast.USub) else v
        if isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Pow)):
            a,b=visit(node.left),visit(node.right)
            if isinstance(node.op,ast.Add): v=a+b
            elif isinstance(node.op,ast.Sub): v=a-b
            elif isinstance(node.op,ast.Mult): v=a*b
            elif isinstance(node.op,ast.Div): v=a/b
            else:
                if abs(b)>100: raise CandidateFault("excessive formula exponent")
                v=a**b
            if not isinstance(v,(int,float)) or not math.isfinite(v): raise CandidateFault("non-finite formula value")
            return v
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in ("exp","log") and len(node.args)==1 and not node.keywords:
            v=visit(node.args[0]);return math.exp(v) if node.func.id=="exp" else math.log(v)
        raise CandidateFault("unsupported formula node")
    return visit(tree)


def need(ok: bool, msg: str) -> None:
    if not ok:
        raise CandidateFault(msg)


def read_ref(test: Path, name: str) -> list[dict[str, str]]:
    path = test / "references" / name
    if not regular_file(path, test/"references") or name not in PINNED_REFERENCES or sha(path) != PINNED_REFERENCES[name]:
        raise EnvironmentFault(f"missing frozen reference table {name}")
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except (OSError, UnicodeError, csv.Error) as e:
        raise EnvironmentFault(f"frozen reference table {name} is unreadable: {e}") from e


def check_columns(data: list[dict], expected: set[str], label: str) -> None:
    need(bool(data), f"{label}: empty table")
    missing = expected - set(data[0])
    need(not missing, f"{label}: missing columns {sorted(missing)}")


def pick(row: dict, *names: str) -> str:
    for n in names:
        if n in row:
            return row[n]
    raise CandidateFault("missing one of required fields: " + ", ".join(names))


def normalized_path(value: str) -> str:
    if not isinstance(value, str): raise CandidateFault("asset path must be a string")
    path = Path(value.strip().replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise CandidateFault("absolute/traversal asset path is not accepted")
    parts = list(path.parts)
    if parts and parts[0] == "assets": parts = parts[1:]
    if parts and parts[0] == "raw_data": parts = parts[1:]
    # Frozen source tables retain the original deposit prefix; strip only that
    # known prefix, never an arbitrary leading directory or a traversal segment.
    if len(parts) >= 3 and parts[0] == "unpacked" and re.fullmatch(r"QC-Files3-[a-f0-9]+", parts[1]) and parts[2] == "QC-Files3": parts = parts[3:]
    elif parts and parts[0] == "QC-Files3": parts = parts[1:]
    return Path(*parts).as_posix() if parts else ""


def criterion(name: str, passed: bool, reason: str, level: str) -> dict:
    return {"name": name, "level": level, "passed": bool(passed), "reason": reason}


def case01(app: Path, final: Path, test: Path) -> list[dict]:
    native = read_ref(test, "native_ibpr_cluster_energies.csv")
    derived = read_ref(test, "derived_ibpr_barriers.csv")
    names = ["profile_rows_complete", "native_quantities_traceable", "barriers_match_published_profile",
             "combination_rule_identified_not_assumed", "saddle_and_electronic_state_consistent"]
    result = {n: False for n in names}
    notes = {n: "" for n in names}
    by_species: dict[str, dict] = {}
    nref = {r["species"].upper(): r for r in native}
    dref = {r["species"].upper(): r for r in derived}
    try:
        candidate = rows(final / "bpr_profile.csv")
        required = {"species", "file_dft", "file_f12", "e_electronic_au", "zpe_au", "e_zero_point_au", "e_f12_au", "derived_kcal_per_mol"}
        check_columns(candidate, required, "bpr_profile.csv")
        by_species = {r["species"].strip().upper(): r for r in candidate}
        output_files_ok = all((final / name).is_file() for name in
                              ("bpr_profile.csv", "bpr_profile.json", "energy_rule.md", "native_parse_manifest.json"))
        result[names[0]] = output_files_ok and len(candidate) == 5 and len(by_species) == 5 and set(by_species) == set(nref)
        if result[names[0]]:
            for row in by_species.values():
                for col in ("e_electronic_au", "zpe_au", "e_zero_point_au", "e_f12_au", "derived_kcal_per_mol"):
                    num(row, col)
                for col in ("file_dft", "file_f12"):
                    rel = Path(row[col])
                    file = app / "assets" / (Path(*rel.parts[1:]) if rel.parts and rel.parts[0] == "assets" else rel)
                    expected_suffix = ".log" if col == "file_dft" else ".out"
                    result[names[0]] &= not rel.is_absolute() and ".." not in rel.parts and rel.suffix == expected_suffix and file.is_file() and not file.is_symlink()
        if result[names[0]]:
            for sp, ref in nref.items():
                result[names[0]] &= Path(by_species[sp]["file_dft"]).name == ref["file_dft"]
                result[names[0]] &= Path(by_species[sp]["file_f12"]).name == ref["file_f12"]
                if sp == "BPR": result[names[0]] &= near(num(by_species[sp], "derived_kcal_per_mol"), 0.0, 1e-8)
        notes[names[0]] = "five unique stationary point rows and all required numeric fields"
    except CandidateFault as e:
        notes[names[0]] = str(e)

    manifest_records = []
    try:
        manifest = json_obj(final / "native_parse_manifest.json")
        manifest_records = manifest.get("records", []) if isinstance(manifest, dict) else manifest
        if not isinstance(manifest_records, list): raise CandidateFault("manifest records must be a list")
        expected_labels = {}
        for sp in nref:
            expected_labels[(sp, "zpe_au")] = ("dft", "Zero-point correction=")
            expected_labels[(sp, "e_zero_point_au")] = ("dft", "Sum of electronic and zero-point Energies=")
            expected_labels[(sp, "e_f12_au")] = ("f12", "RCCSD(T)-F12A/cc-pVDZ-F12 energy=")
        found = {}
        trace_ok = True
        for r in manifest_records:
            if not isinstance(r, dict): trace_ok = False; continue
            key = (str(r.get("species", "")).upper(), str(r.get("quantity", "")))
            if key not in expected_labels or key in found: trace_ok = False; continue
            kind, label = expected_labels[key]
            source = str(r.get("source_file", ""))
            rel = Path(source)
            if rel.is_absolute() or ".." in rel.parts or rel.is_symlink(): trace_ok = False; continue
            if rel.parts and rel.parts[0] == "assets": rel = Path(*rel.parts[1:])
            root = app / "assets"
            p = root / rel
            if not p.is_file() or p.is_symlink(): trace_ok = False; continue
            try: line_no = int(r.get("line_number", 0))
            except (TypeError, ValueError): line_no = 0
            source_lines = p.read_text(errors="replace").splitlines()
            if not (1 <= line_no <= len(source_lines)): trace_ok = False; continue
            line = source_lines[line_no - 1]
            label_record = str(r.get("label", ""))
            if not label_record.strip() or label not in line or label_record.strip() not in line: trace_ok = False; continue
            m = re.search(re.escape(label) + r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?)", line)
            if not m: trace_ok = False; continue
            actual = float(m.group(1).replace("D", "E").replace("d", "e"))
            try: asserted = float(r["value_au"])
            except (KeyError, TypeError, ValueError): trace_ok = False; continue
            if not near(actual, asserted, 5.1e-7): trace_ok = False; continue
            if Path(p).name not in {nref[key[0]]["file_dft"], nref[key[0]]["file_f12"]}: trace_ok = False; continue
            expected_candidate_file = by_species[key[0]]["file_dft" if kind == "dft" else "file_f12"]
            expected_candidate_path = Path(expected_candidate_file)
            expected_asset_rel = Path(*expected_candidate_path.parts[1:]) if expected_candidate_path.parts and expected_candidate_path.parts[0] == "assets" else expected_candidate_path
            if rel != expected_asset_rel: trace_ok = False; continue
            actual_label_lines = [i + 1 for i, source_line in enumerate(source_lines) if label in source_line]
            if not actual_label_lines or line_no != actual_label_lines[-1]: trace_ok = False; continue
            found[key] = asserted
        if len(found) != 15: trace_ok = False
        # Manifest primitives must reproduce the row values, not merely cite files.
        for sp, row in by_species.items():
            for col in ("zpe_au", "e_zero_point_au", "e_f12_au"):
                if (sp, col) not in found or not near(num(row, col), found[(sp, col)], 1e-5): trace_ok = False
            if not near(num(row, "e_electronic_au"), num(row, "e_zero_point_au") - num(row, "zpe_au"), 5e-6): trace_ok = False
        result[names[1]] = trace_ok and result[names[0]]
        notes[names[1]] = "15 native primitive records validated against exact source lines and CSV values"
    except (CandidateFault, KeyError, TypeError, ValueError) as e:
        notes[names[1]] = str(e)

    energy_ok = result[names[0]] and result[names[1]]
    if energy_ok:
        published = {"C1": 18.8, "C2": 17.9, "P-C1": -51.7, "P-C2": -49.4}
        for sp, val in published.items():
            row = by_species[sp]
            calculated = ((num(by_species[sp], "e_f12_au") - num(by_species["BPR"], "e_f12_au")) +
                          (num(by_species[sp], "zpe_au") - num(by_species["BPR"], "zpe_au"))) * HARTREE_KCAL
            energy_ok &= near(num(row, "derived_kcal_per_mol"), calculated, 0.10)
            energy_ok &= near(num(row, "derived_kcal_per_mol"), float(dref[sp]["f12_plus_dft_zpe"]), 0.10)
            energy_ok &= near(num(row, "derived_kcal_per_mol"), val, 0.10)
    result[names[2]] = energy_ok
    notes[names[2]] = "Hartree differences are independently recomputed and compared with all four published values at 0.10 kcal/mol"

    rule_ok = False
    try:
        rule = json_obj(final / "bpr_profile.json")
        rule_text = json.dumps(rule, ensure_ascii=False).lower()
        rule_fields = rule.get("rule", {}) if isinstance(rule, dict) else {}
        if isinstance(rule_fields, dict):
            rule_ok = str(rule_fields.get("electronic_source", "")).lower() in {"f12", "molpro", "coupled_cluster"} and \
                      str(rule_fields.get("correction_source", "")).lower() in {"dft_zpe", "zpe_dft", "gaussian_zpe"} and \
                      str(rule_fields.get("reference_species", "")).upper() == "BPR" and \
                      str(rule_fields.get("unit", "")).lower() in {"kcal/mol", "kcal mol-1"} and \
                      near(float(rule_fields.get("hartree_to_kcal", 0)), HARTREE_KCAL, 0.001)
        else:
            rule_ok = "f12" in rule_text and "zpe" in rule_text
        rule_md = text(final / "energy_rule.md")
        alternatives = {
            "dft_zero_point": [float(dref[x]["dft_zero_point"]) for x in ("C1", "C2", "P-C1", "P-C2")],
            "dft_electronic": [float(dref[x]["dft_electronic"]) for x in ("C1", "C2", "P-C1", "P-C2")],
            "dft_gibbs": [float(dref[x]["dft_gibbs"]) for x in ("C1", "C2", "P-C1", "P-C2")],
            "f12_only": [float(dref[x]["f12_only"]) for x in ("C1", "C2", "P-C1", "P-C2")],
        }
        rejected_schemes = set()
        rejected_records = rule_fields.get("rejected_alternatives", []) if isinstance(rule_fields, dict) else []
        for rec in rejected_records:
            if not isinstance(rec, dict): continue
            scheme = str(rec.get("scheme", "")).lower()
            vector = alternatives.get(scheme)
            supplied = rec.get("values_kcal_per_mol")
            if not vector or not isinstance(supplied, (dict, list)): continue
            try:
                actuals = ([float(supplied[k]) for k in ("C1", "C2", "P-C1", "P-C2")] if isinstance(supplied, dict)
                           else [float(x) for x in supplied])
            except (KeyError, TypeError, ValueError): continue
            section = re.search(rf"(?ms)^## rejected {re.escape(scheme.replace('_', ' '))}\s*\n(.*?)(?=^## |\Z)", rule_md)
            if not section: continue
            predicted_line = re.search(r"c1, c2, p-c1, p-c2:\s*([^\n]+)", section.group(1))
            deviation_line = re.search(r"absolute deviations from the published profile in that order:\s*([^\n]+)", section.group(1))
            try:
                text_values = [float(x) for x in re.findall(r"[-+]?\d+(?:\.\d+)?", predicted_line.group(1))] if predicted_line else []
                text_devs = [float(x) for x in re.findall(r"[-+]?\d+(?:\.\d+)?", deviation_line.group(1))] if deviation_line else []
            except ValueError: text_values, text_devs = [], []
            expected_devs = [abs(v-pub) for v, pub in zip(vector, (18.8, 17.9, -51.7, -49.4))]
            if (len(actuals) == len(text_values) == len(text_devs) == 4 and
                all(near(a, b, 0.02) for a, b in zip(actuals, vector)) and
                all(near(a, b, 0.02) for a, b in zip(text_values, vector)) and
                all(near(a, b, 0.02) for a, b in zip(text_devs, expected_devs))):
                rejected_schemes.add(scheme)
        json_values = rule.get("derived_values_kcal_per_mol", {}) if isinstance(rule, dict) else {}
        json_pub = rule.get("published_values_kcal_per_mol", {}) if isinstance(rule, dict) else {}
        json_agrees = isinstance(json_values, dict) and isinstance(json_pub, dict)
        for sp, pub in (("C1", 18.8), ("C2", 17.9), ("P-C1", -51.7), ("P-C2", -49.4)):
            try:
                json_agrees &= near(float(json_values[sp]), num(by_species[sp], "derived_kcal_per_mol"), 0.01)
                json_agrees &= near(float(json_pub[sp]), pub, 0.01)
            except (KeyError, TypeError, ValueError): json_agrees = False
        result[names[3]] = rule_ok and len(rejected_schemes) >= 2 and energy_ok and json_agrees
        notes[names[3]] = f"machine rule plus {len(rejected_schemes)} distinct measured alternative energy vectors"
    except CandidateFault as e:
        notes[names[3]] = str(e)

    modes_ok = True
    for sp, ref in nref.items():
        path = app / "assets" / "Toluene-iBPR-rearrangment" / ref["file_dft"]
        try:
            source = path.read_text(errors="replace")
            freq_groups = re.findall(r"Frequencies --\s+([^\n]+)", source)
            frequencies = [float(x.replace("D", "E")) for group in freq_groups for x in re.findall(r"[-+]?\d+(?:\.\d+)?", group)]
            charges = re.findall(r"Charge =\s*(-?\d+)\s+Multiplicity =\s*(\d+)", source)
            expected_imag = 1 if sp in {"C1", "C2"} else 0
            modes_ok &= len(frequencies) == 57 and sum(x < 0 for x in frequencies) == expected_imag
            modes_ok &= bool(charges) and int(charges[-1][1]) == 2
            row = by_species.get(sp, {})
            modes_ok &= Path(row.get("file_dft", "")).name == ref["file_dft"]
            orientations = list(re.finditer(r"Standard orientation:", source))
            if not orientations:
                modes_ok = False
            else:
                tail = source[orientations[-1].end():].splitlines()
                atom_lines, separator_count = [], 0
                for line in tail:
                    if re.match(r"\s*-{5,}", line):
                        separator_count += 1
                        if separator_count == 3: break
                        continue
                    if separator_count == 2 and re.match(r"\s*\d+\s+\d+\s+\d+\s+[-+\d.]", line): atom_lines.append(line)
                modes_ok &= len(atom_lines) == 21
        except OSError:
            modes_ok = False
    result[names[4]] = modes_ok and result[names[0]]
    notes[names[4]] = "Gaussian source frequency list, final multiplicity, and profile file assignment independently checked"
    return [
        criterion(n, result[n], notes[n], level) for n, level in zip(names, ("L1", "L2", "L3", "L3", "L3"))
    ]


def classification_name(value: str) -> str:
    token = re.sub(r"[\s_-]+", " ", str(value).strip().lower())
    return {"transition state": "transition_state", "first order saddle": "transition_state",
            "first order saddle point": "transition_state", "minimum": "minimum",
            "higher order saddle": "higher_order_saddle", "higher order saddle point": "higher_order_saddle"}.get(token, token)


def formula_counts(value: str) -> dict[str, int]:
    """Compare element counts, including explicit unit subscripts and reordered elements."""
    value = str(value).strip()
    parts = re.findall(r"([A-Z][a-z]?)(\d*)", value)
    if not parts or "".join(element + count for element, count in parts) != value:
        raise CandidateFault("invalid molecular formula: " + value)
    counts = {}
    for element, count in parts:
        n = int(count or "1")
        if n < 1: raise CandidateFault("nonpositive atom count")
        counts[element] = counts.get(element, 0) + n
    return counts


def case02_rules(rules: object) -> tuple[bool, bool, list[str]]:
    """Accept documented equivalent layouts; conflicting declarations never pass."""
    errors = []
    if not isinstance(rules, dict): return False, False, ["validation_rules.json must be an object"]
    windows = []
    if "conformer_window_kcal_per_mol" in rules: windows.append(rules["conformer_window_kcal_per_mol"])
    retention = rules.get("conformer_retention", {})
    if isinstance(retention, dict) and "window_kcal_per_mol" in retention: windows.append(retention["window_kcal_per_mol"])
    try: window_ok = bool(windows) and all(near(num({"window": v}, "window"), 2.0, 1e-9) for v in windows)
    except CandidateFault: window_ok = False
    if not window_ok: errors.append("conformer retention window missing, conflicting or not 2.0 kcal/mol")
    declarations = []
    if "saddle_rule" in rules: declarations.append(rules["saddle_rule"])
    acceptance = rules.get("saddle_point_acceptance", {})
    accepted_fields = {"acceptance_rule", "require_normal_termination", "normal_termination_required",
                       "exactly_one_imaginary_frequency", "n_imaginary"}
    if isinstance(acceptance, dict) and accepted_fields & set(acceptance):
        # Validate the typed declaration itself so its boolean aliases cannot
        # silently contradict the accompanying text.
        declarations.append(acceptance)
    neg_cue = re.compile(
        r"(?:n't\b|\bnot\b|\bnever\b|\bno\b|\bnone\b|\bwithout\b|\black(?:s|ed|ing)?\b"
        r"|\bfail(?:s|ed|ing)?\b|\bcannot\b|\bcan\s+not\b|\bnor\b|\bneither\b|\bhardly\b"
        r"|\bbarely\b|\bscarcely\b|\babnormal(?:ly)?\b|\bnon[- ]?normal\b)")
    limit_cue = re.compile(
        r"(?:\bat\s+most\b|\bat\s+the\s+most\b|\bat\s+best\b|\bno\s+more\s+than\b|\bnot\s+more\s+than\b"
        r"|\bno\s+greater\s+than\b|\bnot\s+exceeding\b|\bup\s+to\b|\bfewer\s+than\b|\bless\s+than\b"
        r"|\bmaximum\b|\bmax\b|\bmaximally\b|\bor\s+(?:fewer|less|below|under)\b"
        r"|[<≤]\s*=?\s*(?:one|1|two|2|three|3|four|4|0)\b|<=|=<"
        r"|不超过|至多|最多|顶多|少于|低于|以下|以内|之内|左右|约)")
    hedge_cue = re.compile(
        r"(?:\b(?:should|shouldn't|typically|usually|generally|mostly|largely|predominantly|chiefly"
        r"|ordinarily|commonly|frequently|often|sometimes|occasionally|rarely|seldom)\b"
        r"|\bmost\s+(?:of\s+)?(?:the\s+)?(?:transition|saddle|minima|minimum|higher|stationary)\b"
        r"|\bthe\s+majority\s+of\s+(?:the\s+)?(?:transition|saddle|minima|minimum|higher|stationary)\b"
        r"|\b(?:may|might|could|would|can)\s+(?:terminate|end|complete|have|has|show|shows|contain|contains|exhibit|exhibits|require|requires)\b"
        r"|\bexpected\s+to\s+(?:terminate|end|complete|have|show|contain|exhibit|require)\b"
        r"|\b(?:about|roughly|approximately|nearly|almost|around)\s+(?:one|1|two|2|three|3|four|4|zero|0)\b"
        r"|\b(?:in\s+most\s+cases|for\s+the\s+most\s+part|in\s+general|in\s+principle|in\s+theory"
        r"|effectively|virtually|essentially|on\s+average|as\s+a\s+general\s+rule|under\s+normal\s+circumstances"
        r"|presumably|in\s+practice|as\s+a\s+rule|where\s+possible|if\s+possible|almost\s+always|generally\s+speaking)\b"
        r"|\bnormally\s+(?:have|has|show|shows|contain|contains|exhibit|exhibits|require|requires)\b"
        r"|大致|大约|大概|通常|一般|往往|可能|也许|或许|应该|应当|多数情况|一般情况下|大都|大多|多半|多数|个别|有时|偶尔|一般来说|原则上|在实践中)")
    zh_neg = re.compile(r"(?:不|未|无|非|没有|并非|不是|不能|不可|无法|不必|无须|缺|缺少|异常)")
    zero_claim = re.compile(
        r"(?:(?:zero|0)\s+(?:negative|imaginary)(?:\s+(?:harmonic\s+)?frequenc(?:y|ies))?"
        r"|(?:no|none|without)\s+(?:any\s+)?(?:negative|imaginary)(?:\s+(?:harmonic\s+)?frequenc(?:y|ies))?"
        r"|(?:must|should|may|can)\s+not\s+(?:have|show|contain|exhibit)\s+(?:any\s+)?(?:negative|imaginary)"
        r"|(?:have|has|contains?|shows?|exhibits?)\s+none"
        r"|(?:零|0|没有|无|无任何)\s*(?:个)?\s*(?:负频|虚频)"
        r"|(?:不|未)(?:出现|存在)\s*(?:任何)?\s*(?:负频|虚频)"
        r"|(?:不得|不能|不可|不允许)(?:有|出现|存在)\s*(?:任何)?\s*(?:负频|虚频)"
        r"|(?:负频|虚频)\s*(?:为零|为0|是0))")
    exactly_one_claim = re.compile(
        r"(?:(?:exactly|only)\s+(?:one|1)\s+(?:negative|imaginary)"
        r"|(?<![>≥=<])(?<![>≥=<]\s)(?<!than )(?<!least )(?:one|1)\s+(?:negative|imaginary))"
        r"|(?<!于)(?<!过)(?<!少)(?:恰有|恰好|仅有|只有)?\s*(?:一个|1个)\s*(?:负频|虚频)")
    at_least_two_claim = re.compile(
        r"(?:(?:two|2|three|3|four|4|five|5|six|6|seven|7|eight|8|nine|9)\s+or\s+more"
        r"|at\s+least\s+(?:two|2|three|3|four|4)"
        r"|more\s+than\s+(?:one|1)"
        r"|multiple"
        r"|(?:≥|>=)\s*(?:two|2|three|3|four|4)"
        r"|>\s*(?:one|1|two|2|three|3)"
        r"|(?:two|2|three|3|four|4|five|5|six|6|seven|7|eight|8|nine|9))\s+(?:negative|imaginary)"
        r"|(?:两个或更多|两个以上|至少两个|超过一个|多于一个|多于1|不少于两个|多个|两个|2个)\s*(?:负频|虚频)"
        r"|(?:大于|不少于|不低于|至少)\s*(?:一个|1个|两个|2个)\s*(?:负频|虚频)")
    higher_contrast = re.compile(
        r"(?:(?:is|are)\s+not\s+(?:accepted\s+as\s+)?(?:a\s+)?transition\s+states?"
        r"|(?:is|are)\s+not\s+a\s+transition\s+state"
        r"|rejected\s+as\s+(?:a\s+)?transition\s+states?"
        r"|不作为过渡态|不是过渡态)")
    higher_positive_negation = re.compile(
        r"(?:not\s+less\s+than|no\s+less\s+than|no\s+fewer\s+than|not\s+fewer\s+than)\s+(?:two|2|three|3|four|4)\s+(?:negative|imaginary)"
        r"|(?:不低于|不少于)\s*(?:两个|2个|三个|3个|四个|4个)\s*(?:负频|虚频)")
    normal_ok = r"normal termination|normal completion|terminat(?:e|es|ed|ing) normally|end(?:s|ed|ing)? normally|normally terminated|termination\s+(?:is|was)\s+normal|ended normally|completed normally|must terminate normally|must be normally terminated|正常终止|正常结束|正常完成|须正常终止"
    def role_ok(role, clause, global_normal_roles):
        text = clause
        if hedge_cue.search(text): return False
        if role == "transition":
            if limit_cue.search(text): return False
            text = re.sub(r"\bnot\s+only\b", " ", text)
            text = re.sub(r"\bnot\s+(?:a\s+)?higher[\s_-]*order(?:[\s_-]*saddle)?", " ", text)
            text = re.sub(r"(?:不是|非)\s*高阶鞍点", " ", text)
            if not exactly_one_claim.search(text): return False
            if at_least_two_claim.search(text): return False
            if neg_cue.search(text) or zh_neg.search(text): return False
            return bool(re.search(normal_ok, text)) or role in global_normal_roles
        if role == "minimum":
            text, zeros = zero_claim.subn(" ", text)
            if not zeros: return False
            if exactly_one_claim.search(text) or at_least_two_claim.search(text): return False
            if limit_cue.search(text): return False
            return not (neg_cue.search(text) or zh_neg.search(text))
        if role == "higher":
            text, _ = higher_contrast.subn(" ", text)
            text, positive = higher_positive_negation.subn(" ", text)
            text = re.sub(r"\bnot\s+only\b", " ", text)
            bare_positive = re.search(
                r"\b(?:two|2|three|3|four|4|five|5|six|6|seven|7|eight|8|nine|9)\b\s*$"
                r"|\b(?:two|2|three|3|four|4)\s+or\s+more\s*$"
                r"|\bat\s+least\s+(?:two|2|three|3|four|4)\s*$"
                r"|\bmore\s+than\s+(?:one|1)\s*$"
                r"|(?:两个|2个)\s*$"
                r"|(?:两个或更多|至少两个|超过一个|多于一个|多个)\s*$",
                text)
            if not (positive or bare_positive or at_least_two_claim.search(text)): return False
            if limit_cue.search(text): return False
            if exactly_one_claim.search(text) or zero_claim.search(text): return False
            return not (neg_cue.search(text) or zh_neg.search(text))
        return True
    def valid_text(value):
        declared = str(value).lower()
        if hedge_cue.search(declared): return False
        clauses = re.split(r"[\n;.!?。；！？]+|,\s*(?=(?:a\s+|an\s+|the\s+)?(?:transition[\s_-]*state|first.order saddle|saddle|\bts\b|minimum|higher.order|过渡态|鞍点|极小点|高阶))|，\s*(?=(?:transition[\s_-]*state|saddle|\bts\b|minimum|higher.order|过渡态|鞍点|极小点|高阶))|\band\s+(?=(?:a\s+|an\s+|the\s+)?(?:transition[\s_-]*state|first.order saddle|saddle|\bts\b|minimum|higher.order))|(?:且|和|并且)\s*(?=(?:过渡态|鞍点|极小点|高阶))|\b(?:whereas|while|but)\b", declared)
        higher = r"higher[\s_-]*order(?:[\s_-]*saddle)?|高阶鞍点"
        minimum = r"\bmin(?:imum|ima)\b|极小(?:点)?"
        transition = r"\btransition[\s_-]*state\b|\bfirst[ -]order saddle\b|\bsaddle(?: point)?\b|\bts\b|过渡态|鞍点"
        roles = []
        current_role = "transition"
        global_normal_roles = set()
        for clause in filter(None, (c.strip() for c in clauses)):
            clause = re.sub(r"\b(?:without\s+(?:exception|fail)|no\s+doubt)\b", " ", clause)
            # A separate affirmative normal-termination constraint can apply to
            # all accepted structures; it supplements, but cannot replace, the
            # transition-state clause that establishes exactly one imaginary mode.
            if (re.search(normal_ok, clause) and
                    not re.search(r"imaginary|negative|frequenc|虚频|负频|频率", clause)):
                required_normal = re.search(
                    r"\b(?:required|requiredly|requires?|must|shall|mandatory)\b|必须|须|要求", clause)
                weak_normal = re.search(
                    r"\b(?:sufficient|suffices?|enough|optional(?:ly)?|only|merely)\b|足够|充分|可选", clause)
                if (not required_normal or weak_normal or hedge_cue.search(clause)
                        or neg_cue.search(clause) or zh_neg.search(clause)
                        or limit_cue.search(clause)):
                    return False
                all_stationary = bool(re.search(
                    r"\b(?:all|every)\s+(?:stationary\s+points?|structures?|accepted\s+structures?)\b", clause))
                both_classes = (bool(re.search(transition, clause)) and bool(re.search(minimum, clause)))
                if all_stationary or both_classes:
                    global_normal_roles.update(("transition", "minimum"))
                continue
            if not re.search(r"imaginary|negative|frequenc|terminat|normal|虚频|负频|频率|正常|一个|1个|两个|2个|零|zero|none|\b(?:one|two|three|four|five|six|seven|eight|nine|multiple)\b|\b[1-9]\b", clause):
                continue
            higher_negated = re.search(r"(?:not\s+(?:a\s+)?|rather than\s+(?:a\s+)?)higher[\s_-]*order(?:[\s_-]*saddle)?|(?:非|不是|而非)\s*高阶鞍点", clause)
            if re.search(higher, clause) and not higher_negated: role = "higher"
            elif re.search(minimum, clause): role = "minimum"
            elif re.search(transition, clause): role = "transition"
            else: role = current_role
            current_role = role
            if roles and roles[-1][0] == role: roles[-1] = (role, roles[-1][1] + " " + clause)
            else: roles.append((role, clause))
        if not any(role == "transition" for role, _ in roles): return False
        return all(role_ok(role, clause, global_normal_roles) for role, clause in roles)
    def valid(declared):
        if not isinstance(declared, dict): return valid_text(declared)
        text_present = "acceptance_rule" in declared
        text_ok = valid_text(declared["acceptance_rule"]) if text_present else True
        normal_values = [declared[k] for k in ("require_normal_termination", "normal_termination_required") if k in declared]
        freq_values = []
        if "exactly_one_imaginary_frequency" in declared:
            freq_values.append(declared["exactly_one_imaginary_frequency"] is True)
        if "n_imaginary" in declared:
            try: freq_values.append(num(declared, "n_imaginary") == 1)
            except CandidateFault: return False
        bool_fields_ok = all(type(v) is bool for v in normal_values) and len(set(normal_values)) <= 1
        freq_fields_ok = len(set(freq_values)) <= 1
        normal_ok = bool(normal_values) and bool_fields_ok and normal_values[0] is True
        freq_ok = bool(freq_values) and freq_fields_ok and freq_values[0] is True
        if text_present:
            normal_ok = normal_ok if normal_values else text_ok
            freq_ok = freq_ok if freq_values else text_ok
        return bool(text_ok and normal_ok and freq_ok)
    saddle_ok = bool(declarations) and all(valid(d) for d in declarations)
    if not saddle_ok: errors.append("saddle rule must require normal termination and exactly one imaginary frequency")
    return window_ok, saddle_ok, errors


def energy_quantity_is_zpe(value: str) -> bool:
    quantity = value.lower()
    normalized = re.sub(r"[-]+", " ", re.sub(r"\+", " plus ", quantity))
    if re.search(r"\b(?:not|without|w/o|no|excluding|exclude)\s+(?:the\s+)?(?:zero[ -]point|zpe)\b"
                 r"|\b(?:zero[ -]point|zpe)\s+(?:is\s+)?(?:not\b|excluded|omitted)"
                 r"|\b(?:zero[ -]point(?:\s+energies?)?|zpe)(?:\s+\w+){0,3}\s+not\b"
                 r"|\bexcludes?\s+(?:the\s+)?(?:zero[ -]point|zpe)\b", quantity):
        return False
    if re.search(r"\b(?:gibbs|free energy|thermal|enthalp(?:y|ies)|helmholtz)\b", normalized):
        return False
    electronic_zpe = re.search(
        r"\belectronic(?:\s+energy)?\s+(?:plus|and)\s+(?:zero[ -]point(?:\s+energy)?|zpe)"
        r"(?:\s+(?:energy|energies|correction))?\b", normalized)
    return (quantity in {"sum of electronic and zero-point energies (zpe)", "zpe",
                         "electronic+zpe", "electronic plus zpe", "e0", "e_electronic+zpe"}
            or "sum of electronic and zero-point energies" in quantity
            or bool(electronic_zpe)
            or bool(re.search(r"\belectronic\s+plus\s+zero\s+point\s+sum\b", normalized)))


def gaussian_sum_from_latest_frequency(source: str) -> tuple[float, float]:
    """Return SCF + ZPE and Gaussian's rounded sum for the latest frequency job."""
    harmonic = source.rfind("Harmonic frequencies")
    need(harmonic >= 0, "native Gaussian harmonic-frequency block missing")
    zpe_match = re.search(r"Zero-point correction=\s*([-+0-9.Ee]+)", source[harmonic:])
    need(zpe_match is not None, "latest Gaussian frequency block lacks a ZPE correction")
    zpe_at = harmonic + zpe_match.start()
    sum_match = re.search(r"Sum of electronic and zero-point Energies=\s*([-+0-9.Ee]+)", source[zpe_at:])
    need(sum_match is not None, "latest Gaussian frequency block lacks its electronic-plus-ZPE sum")
    frequency_block = source[harmonic:zpe_at]
    need(bool(re.search(r"Frequencies --", frequency_block)), "latest Gaussian frequency block is incomplete")
    scf_values = re.findall(r"SCF Done:\s+E\([^\n]*?\)\s*=\s*([-+0-9.Ee]+)", source[:harmonic])
    need(bool(scf_values), "native SCF energy preceding latest frequency block missing")
    scf_text = scf_values[-1]
    zpe_text = zpe_match.group(1)
    sum_text = sum_match.group(1)
    scf = float(scf_text)
    zpe = float(zpe_text)
    printed_sum = float(sum_text)
    computed_sum = scf + zpe
    def half_rounding_unit(token):
        mantissa, _, exponent = token.lower().partition("e")
        decimals = len(mantissa.partition(".")[2])
        power = int(exponent) if exponent else 0
        return 0.5 * 10 ** (power - decimals)
    rounding_bound = (half_rounding_unit(scf_text) + half_rounding_unit(zpe_text)
                      + half_rounding_unit(sum_text) + 1e-12)
    need(abs(computed_sum - printed_sum) <= rounding_bound,
         "native SCF plus ZPE does not reproduce Gaussian's rounded sum")
    return computed_sum, printed_sum


def case02(app: Path, final: Path, test: Path) -> list[dict]:
    census = read_ref(test, "native_gaussian_census.csv")
    members = read_ref(test, "derived_conformer_members.csv")
    barriers = read_ref(test, "derived_si_table7_isomer_barriers.csv")
    audit_errors, conformer_errors, barrier_errors = [], [], []
    mode_failures = []
    census_ok = mode_ok = partition_ok = levels_ok = False
    member_ok = select_ok = alias_ok = False
    barrier_ok = False
    expected_by_path = {normalized_path(r["relative_path"]): r for r in census}
    audit_by_path = {}
    audit = []
    try:
        audit = rows(final / "saddle_audit.csv")
        check_columns(audit, {"file", "level", "multiplicity", "n_atoms", "formula", "n_modes", "n_imaginary",
                              "imaginary_freq_cm1", "classification", "normal_termination"}, "saddle_audit.csv")
        expected_by_path = {normalized_path(r["relative_path"]): r for r in census}
        audit_by_path = {}
        for row in audit:
            source = normalized_path(pick(row, "file"))
            # The public audit contract supplies separate file/directory fields.
            # Resolve their combination before matching the native census.
            if len(Path(source).parts) == 1 and row.get("directory", "").strip():
                directory = normalized_path(row["directory"])
                source = (Path(directory) / source).as_posix()
            audit_by_path[source] = row
        census_ok = len(audit) == len(census) == 196 and len(audit_by_path) == 196 and set(audit_by_path) == set(expected_by_path)
        mode_ok = census_ok
        for path, ref in expected_by_path.items():
            row = audit_by_path.get(path)
            if not row: continue
            try:
                asset = app / "assets" / path
                if not asset.is_file() or asset.is_symlink(): mode_ok = False; continue
                source = asset.read_text(errors="replace")
                nat_match = re.findall(r"NAtoms=\s*(\d+)", source)
                charges = re.findall(r"Charge =\s*(-?\d+)\s+Multiplicity =\s*(\d+)", source)
                harm = source.rfind("Harmonic frequencies")
                zpe_at = source.find("Zero-point correction=", harm)
                freq_section = source[harm:zpe_at if zpe_at >= 0 else None]
                native_freqs = [float(x) for line in re.findall(r"Frequencies --([^\n]+)", freq_section)
                                for x in re.findall(r"[-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?", line)]
                orientation = source.rfind("Standard orientation:")
                tail = source[orientation:] if orientation >= 0 else ""
                atom_nums = []
                sep_count = 0
                for line in tail.splitlines()[1:]:
                    if re.match(r"\s*-{5,}", line):
                        sep_count += 1
                        if sep_count >= 3: break
                        continue
                    if sep_count == 2:
                        m = re.match(r"\s*\d+\s+(\d+)\s+\d+\s+", line)
                        if m: atom_nums.append(int(m.group(1)))
                element = {1:"H",6:"C",7:"N",8:"O",9:"F",15:"P",16:"S",17:"Cl"}
                counts = {}
                for anum in atom_nums: counts[element.get(anum, f"X{anum}")] = counts.get(element.get(anum, f"X{anum}"),0)+1
                formula = "".join(e+(str(counts[e]) if counts[e] != 1 else "") for e in ("C","H") if e in counts)
                formula += "".join(e+(str(counts[e]) if counts[e] != 1 else "") for e in sorted(counts) if e not in {"C","H"})
                route = " ".join(line.strip().lower() for line in source.splitlines() if re.match(r"\s*#",line))
                expected_level = ref["level"].lower().replace(" ", "")
                if "b3lyp" in expected_level: native_level = "b3lyp" in route and ("6-31+g(d)" in route.replace(" ", "") or "6-31+g*" in route.replace(" ", ""))
                else:
                    route_norm = route.replace(" ", "").replace("-", "")
                    native_level = "wb97xd" in route_norm and "augccpvtz" in route_norm
                nat = int(nat_match[-1]) if nat_match else -1
                imag_values = [x for x in native_freqs if x < 0]
                modes, imag = len(native_freqs), len(imag_values)
                mode_ok &= nat == num(row,"n_atoms") == len(atom_nums)
                expected_modes = 3*nat-5 if formula == "NO" and nat == 2 else 3*nat-6
                mode_ok &= modes == num(row,"n_modes") == expected_modes and imag == num(row,"n_imaginary") == int(float(ref["n_imaginary"]))
                mode_ok &= formula_counts(formula) == formula_counts(row["formula"]) == formula_counts(ref["formula"]) and native_level
                mode_ok &= classification_name(row["classification"]) == classification_name(ref["class"])
                mode_ok &= level_name(row["level"]) == level_name(ref["level"])
                mode_ok &= bool(charges) and near(float(row["multiplicity"]), float(charges[-1][1]), 1e-6) and near(float(charges[-1][1]), float(ref["multiplicity"]),1e-6)
                claimed_imag = [float(x) for x in re.findall(r"[-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?", row["imaginary_freq_cm1"])]
                mode_ok &= len(claimed_imag) == len(imag_values) and all(any(near(x,y,0.05) for y in imag_values) for x in claimed_imag)
                mode_ok &= "normal termination of gaussian" in source.lower()
                mode_ok &= row["normal_termination"].lower() in {"true", "yes", "1"}
            except (CandidateFault, ValueError, KeyError, TypeError): mode_ok = False
        counts = {c: sum(1 for r in audit if classification_name(r.get("classification", "")) == c)
                  for c in ("transition_state", "minimum", "higher_order_saddle")}
        partition_ok = counts.get("transition_state") == 79 and counts.get("minimum") == 117 and \
                       counts.get("higher_order_saddle") == 0 and all(r.get("normal_termination", "").lower() in {"true", "yes", "1"} for r in audit)
        levels = {"wB97XD/aug-cc-pVTZ": 191, "B3LYP/6-31+G(d)": 5}
        level_counts = {k: sum(1 for r in audit if level_name(r.get("level", "")) == level_name(k)) for k in levels}
        levels_ok = level_counts == levels
    except (CandidateFault, KeyError, ValueError, TypeError) as e:
        audit_errors.append(str(e))
    audit_table_failed = bool(audit_errors)
    candidate_to_family, family_to_candidate = {}, {}
    submitted = []
    try:
        member_file = final / "conformer_members.csv"
        member_ok = False
        if member_file.is_file():
            submitted = rows(member_file)
            check_columns(submitted, {"relative_path", "family_id", "level", "zpe_au", "delta_from_family_min_kcal_per_mol", "within_2_kcal", "selected_lowest"}, "conformer_members.csv")
            expected_members = {normalized_path(r["relative_path"]): r for r in members}
            actual_members = {normalized_path(r["relative_path"]): r for r in submitted}
            member_ok = len(submitted) == len(actual_members) == len(expected_members) and set(actual_members) == set(expected_members)
            for path, ref in expected_members.items():
                row = actual_members.get(path, {})
                try:
                    supplied_family, expected_family = row["family_id"], ref["family_id"]
                    if not supplied_family: member_ok = False
                    member_ok &= candidate_to_family.setdefault(supplied_family, expected_family) == expected_family
                    member_ok &= family_to_candidate.setdefault(expected_family, supplied_family) == supplied_family
                    member_ok &= level_name(row["level"]) == level_name(ref["level"])
                    submitted_e0 = float(row["zpe_au"])
                    native_e0_ok = near(submitted_e0, float(ref["zpe_au"]), 5e-7)
                    if not native_e0_ok:
                        try:
                            asset = app / "assets" / path
                            computed_e0, _ = gaussian_sum_from_latest_frequency(asset.read_text(errors="replace"))
                            native_e0_ok = near(submitted_e0, computed_e0, 5e-7)
                        except (OSError, CandidateFault, ValueError):
                            native_e0_ok = False
                    member_ok &= native_e0_ok
                    member_ok &= near(float(row["delta_from_family_min_kcal_per_mol"]), float(ref["delta_from_family_min_kcal_per_mol"]), 0.05)
                    member_ok &= disposition(row["within_2_kcal"]) == disposition(ref["within_2_kcal"]) and disposition(row["selected_lowest"]) == disposition(ref["selected_lowest"])
                except (CandidateFault, KeyError, ValueError, TypeError): member_ok = False
        notes = text(final / "audit_notes.md")
        alias_ok = "r1" in notes and any(x in notes for x in ("alias", "conf", "别名", "构象"))
        selection = rows(final / "conformer_selection.csv")
        check_columns(selection, {"reaction_key", "n_conformers_found", "selected_file", "energy_quantity_used", "spread_within_window_kcal_per_mol"}, "conformer_selection.csv")
        expected_groups: dict[str, list[dict]] = {}
        for member in members: expected_groups.setdefault(member["family_id"], []).append(member)
        selected_by_key = {candidate_to_family.get(r["reaction_key"], r["reaction_key"]): r for r in selection}
        select_ok = len(selection) == len(selected_by_key) == len(expected_groups) == 118 and set(selected_by_key) == set(expected_groups)
        for family, group in expected_groups.items():
            row = selected_by_key.get(family)
            if row is None: select_ok = False; continue
            min_member = min(group, key=lambda x: float(x["zpe_au"]))
            retained = [float(x["delta_from_family_min_kcal_per_mol"]) for x in group if x["within_2_kcal"] == "yes"]
            expected_spread = max(retained)-min(retained) if retained else float("nan")
            select_ok &= num(row,"n_conformers_found") == len(group)
            select_ok &= normalized_path(row["selected_file"]) == normalized_path(min_member["relative_path"])
            select_ok &= energy_quantity_is_zpe(pick(row,"energy_quantity_used"))
            select_ok &= near(float(row["spread_within_window_kcal_per_mol"]), expected_spread, 0.05)
    except (CandidateFault, KeyError, ValueError, TypeError) as e:
        conformer_errors.append(str(e))
    # Recompute each channel from the public Gaussian ZPE and Molpro F12 energy
    # files; never accept the candidate's barrier number as its own evidence.
    barrier_ok = False
    try:
        submitted_barriers = rows(final / "isomer_barriers.csv")
        check_columns(submitted_barriers, {"site", "channel", "minimum_dft", "minimum_f12", "saddle_dft", "saddle_f12",
                                          "composite_kcal_per_mol", "published_kcal_per_mol", "deviation_kcal_per_mol"}, "isomer_barriers.csv")
        sites = {"ipso": "iBPR", "meta": "mBPR", "para": "pBPR", "ortho": "OBPR"}
        submitted_map = {(r["site"].lower(), r["channel"].upper()): r for r in submitted_barriers}
        barrier_ok = len(submitted_map) == 8 and len(submitted_barriers) == 8
        def gaussian_zpe(path: Path) -> float:
            vals = re.findall(r"Zero-point correction=\s*([-+0-9.Ee]+)", path.read_text(errors="replace"))
            if not vals: raise CandidateFault(f"no Gaussian ZPE in {path.name}")
            return float(vals[-1])
        def molpro_f12(path: Path) -> float:
            vals = re.findall(r"RCCSD\(T\)-F12A/cc-pVDZ-F12 energy=\s*([-+0-9.Ee]+)", path.read_text(errors="replace"))
            if not vals: raise CandidateFault(f"no F12A energy in {path.name}")
            return float(vals[-1])
        # The SI reports the lowest channel per site, while Source Data also
        # supplies channel-resolved ipso barriers. Both are published references;
        # a deviation must be computed against the value the row actually uses.
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with zipfile.ZipFile(app / "assets/41467_2023_40675_MOESM3_ESM.xlsx") as workbook:
            sheet = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        ipso_profile = {}
        for channel, cell in (("C1", "B4"), ("C2", "D8")):
            value = sheet.find(f".//s:c[@r='{cell}']/s:v", ns)
            if value is None or value.text is None:
                raise EnvironmentFault("published channel reference missing from Source Data")
            ipso_profile[channel] = float(value.text)
        for site, base in sites.items():
            for channel in ("C1", "C2"):
                row = submitted_map.get((site, channel))
                if not row: barrier_ok = False; continue
                dft_min_name = f"Toluene-{base}-DFT.log" if site != "ortho" else "Toluene-oBPR-DFT.log"
                dft_ts_name = f"Toluene-{base}-TS-{channel}-DFT.log"
                f12_base = base
                f12_min_name = f"Toluene-{f12_base}-F12.out"
                f12_ts_name = f"Toluene-{f12_base}-TS-{channel}-F12.out"
                if site == "ortho": f12_min_name = "Toluene-OBPR-F12.out"
                paths = [app / "assets/Figure4/Toluene" / x for x in (dft_min_name, f12_min_name, dft_ts_name, f12_ts_name)]
                try:
                    barrier_ok &= all(submitted_path_matches(app,row[k],path) for k,path in zip(("minimum_dft","minimum_f12","saddle_dft","saddle_f12"),paths))
                    composite = ((molpro_f12(paths[3])-molpro_f12(paths[1]))+(gaussian_zpe(paths[2])-gaussian_zpe(paths[0])))*627.509474063
                    barrier_ok &= near(num(row,"composite_kcal_per_mol"),composite,0.02)
                    expected_published = {"ipso":17.9,"meta":21.0,"para":22.0,"ortho":23.2}[site]
                    published_value = num(row,"published_kcal_per_mol")
                    references = [expected_published]
                    if site == "ipso": references.append(ipso_profile[channel])
                    barrier_ok &= any(near(published_value,value,0.02) for value in references)
                    barrier_ok &= near(abs(num(row,"deviation_kcal_per_mol")),abs(composite-published_value),0.02)
                except (OSError, CandidateFault, ValueError): barrier_ok = False
        site_min = {}
        for site in sites:
            entries = [r for (s,_),r in submitted_map.items() if s == site]
            if len(entries) == 2:
                site_min[site] = min(num(r,"composite_kcal_per_mol") for r in entries)
        barrier_ok &= all(site in site_min for site in sites)
        barrier_ok &= all(near(site_min[s],v,0.20) for s,v in {"ipso":17.9,"meta":21.0,"para":22.0}.items())
        barrier_ok &= near(site_min.get("ortho", float("nan")),24.39,0.03) and abs(site_min.get("ortho",0)-23.2)>1.0
    except (CandidateFault, KeyError, ValueError, TypeError) as e:
        barrier_errors.append(str(e))
    try:
        window_ok, saddle_rule_ok, rule_errors = case02_rules(json_obj(final / "validation_rules.json"))
    except CandidateFault as e:
        window_ok = saddle_rule_ok = False
        rule_errors = ["saddle rule: " + str(e), "conformer retention rule: " + str(e)]
    mode_ok &= saddle_rule_ok
    member_ok &= window_ok
    audit_errors.extend(e for e in rule_errors if "saddle" in e)
    conformer_errors.extend(e for e in rule_errors if "saddle" not in e)
    for path, ref in expected_by_path.items():
        try: levels_ok &= path in audit_by_path and near(num(audit_by_path[path], "multiplicity"), float(ref["multiplicity"]), 1e-6)
        except CandidateFault: levels_ok = False
    if audit_table_failed: census_ok = mode_ok = partition_ok = levels_ok = False
    if conformer_errors: member_ok = select_ok = False
    if barrier_errors: barrier_ok = False
    conformer_summary = (f"members={len(submitted)}/{len(members)}; families={len(candidate_to_family)}/{len({r['family_id'] for r in members})}; "
                         f"member_values_and_partition={member_ok}; selection={select_ok}; R1_alias={alias_ok}; window={window_ok}")
    return [
        criterion("audit_table_covers_deposit", census_ok, "one audit row for each of 196 native logs" + ("; " + "; ".join(audit_errors) if audit_errors else ""), "L1"),
        criterion("mode_count_and_classification_consistent", mode_ok, "native mode counts (NO: 3N-5), imaginary counts, element counts, classification and saddle rule" + ("; " + "; ".join(audit_errors) if audit_errors else ""), "L2"),
        criterion("saddle_minimum_partition_reproduced", partition_ok, "79 first-order saddles, 117 minima, no higher saddles or abnormal terminations", "L3"),
        criterion("levels_and_electronic_states_identified", levels_ok, "191 wB97XD and 5 B3LYP; all parsed rows have multiplicity", "L3"),
        criterion("conformer_window_applied_explicitly", member_ok and select_ok and alias_ok, conformer_summary + ("; " + "; ".join(conformer_errors) if conformer_errors else ""), "L3"),
        criterion("isomer_barriers_reproduced", barrier_ok, "ipso/meta/para barriers and ortho published discrepancy disclosed" + ("; " + "; ".join(barrier_errors) if barrier_errors else ""), "L3"),
    ]


def case03(app: Path, final: Path, test: Path) -> list[dict]:
    names = ["rate_table_complete_per_temperature", "rates_read_from_analysis_block", "rates_match_published_table",
             "fit_within_measured_curvature", "branching_validity_range_stated", "fixed_pressure_scope_reported"]
    result = {n: False for n in names}; reason = {n: "" for n in names}
    reference = read_ref(test, "mesmer_tdep_rates.csv")
    published = read_ref(test, "SD_figure1c_arrhenius.csv")
    # Native filenames are stable identifiers; CSV source_file may be asset-relative.
    expected = {Path(r["file"]).name: r for r in reference}
    rates = rows(final / "rates_by_temperature.csv")
    required = {"source_file", "temperature_K", "pressure_Torr", "bath_gas", "k_C1_per_s", "k_C2_per_s", "k_total_per_s",
                "C1_fromRef", "C1_toRef", "C2_fromRef", "C2_toRef"}
    check_columns(rates, required, "rates_by_temperature.csv")
    actual = {Path(pick(r, "source_file")).name: r for r in rates}
    try:
        unique_t = {round(num(r, "temperature_K"), 6) for r in rates}
        all_outputs_parseable = (final / "arrhenius_fit.json").is_file() and (final / "branching_curve.csv").is_file() and (final / "derivation_notes.md").is_file()
    except CandidateFault:
        unique_t = set(); all_outputs_parseable = False
    result[names[0]] = len(rates) == len(actual) == len(expected) == len(unique_t) == 23 and set(actual) == set(expected) and all_outputs_parseable
    reason[names[0]] = "23 unique temperature/source rows and complete output files" if result[names[0]] else "expected 23 unique source files and temperatures"
    xml_ok = result[names[0]]
    for file, ref in expected.items():
        row = actual.get(file)
        if row is None: xml_ok = False; continue
        rel = Path(str(row["source_file"]))
        if rel.is_absolute() or ".." in rel.parts: xml_ok = False; continue
        if rel.parts and rel.parts[0] == "assets": rel = Path(*rel.parts[1:])
        matches = list((app / "assets").rglob(Path(file).name))
        source_path = app / "assets" / rel
        if len(matches) != 1 or source_path.resolve() != matches[0].resolve() or source_path.is_symlink(): xml_ok = False; continue
        try:
            import xml.etree.ElementTree as ET
            root = ET.parse(source_path).getroot()
            ns = {"me": "http://www.chem.leeds.ac.uk/mesmer"}
            pt = root.find(".//me:PTpair", ns)
            lists = root.findall(".//me:analysis/me:rateList", ns)
            if pt is None or len(lists) != 1: xml_ok = False; continue
            rate_list = lists[0]
            rxns = rate_list.findall("me:firstOrderRate", ns)
            by_to = {x.attrib.get("toRef"): x for x in rxns}
            c1, c2 = by_to.get("ringopen-prod1"), by_to.get("ringopen-prod2")
            if len(rxns) != 2 or c1 is None or c2 is None: xml_ok = False; continue
            t, pressure = float(pt.attrib["T"]), float(pt.attrib["P"])
            k1, k2 = float(c1.text), float(c2.text)
            xml_ok &= c1.attrib.get("fromRef") == row["C1_fromRef"] == "RO2"
            xml_ok &= c1.attrib.get("toRef") == row["C1_toRef"] == "ringopen-prod1"
            xml_ok &= c2.attrib.get("fromRef") == row["C2_fromRef"] == "RO2"
            xml_ok &= c2.attrib.get("toRef") == row["C2_toRef"] == "ringopen-prod2"
            xml_ok &= near(num(row, "temperature_K"), t, 1e-8) and near(num(row, "pressure_Torr"), pressure, 1e-8)
            xml_ok &= near(num(row, "k_C1_per_s"), k1, 1e-4, rel=True) and near(num(row, "k_C2_per_s"), k2, 1e-4, rel=True)
            xml_ok &= near(num(row, "k_total_per_s"), k1 + k2, max(1e-30, (k1+k2)*1e-6))
            xml_ok &= row["bath_gas"].upper() == pt.attrib.get("bathGas", "").upper() == "N2"
            xml_ok &= rate_list.attrib.get("units") == "s-1"
        except (OSError, ET.ParseError, KeyError, ValueError, TypeError): xml_ok = False
    result[names[1]] = xml_ok
    reason[names[1]] = "two analysis firstOrderRate elements, species refs, PTpair metadata and values checked against XML" if xml_ok else "candidate does not match both native first-order rates and species references"

    pub_map = {(round(float(r["temperature_K"]), 6), r["block"]): r for r in published}
    pub_ok = result[names[1]]
    for row in rates:
        t = round(num(row, "temperature_K"), 6)
        ref = expected.get(Path(pick(row, "source_file")).name)
        if ref is None:
            pub_ok = False
            continue
        block = ref["source_data_block"]
        if block == "absent": continue
        p = pub_map.get((t, block))
        if p is None: pub_ok = False; continue
        pub_ok &= near(num(row, "k_C1_per_s"), float(p["k_C1_per_s"]), 1e-4, rel=True)
        pub_ok &= near(num(row, "k_C2_per_s"), float(p["k_C2_per_s"]), 1e-4, rel=True)
    result[names[2]] = pub_ok
    reason[names[2]] = "all shared published temperatures match the frozen source-data table within 1e-4 relative"

    fits = json_obj(final / "arrhenius_fit.json")
    if isinstance(fits, dict):
        fit_records = {str(k).lower(): v for k, v in fits.items()}
        if isinstance(fits.get("fits"), list): fit_records = {str(v.get("quantity", "")).lower(): v for v in fits["fits"] if isinstance(v, dict)}
    elif isinstance(fits, list): fit_records = {str(v.get("quantity", "")).lower(): v for v in fits if isinstance(v, dict)}
    else: fit_records = {}
    series = {"c1": [num(r, "k_C1_per_s") for r in rates], "c2": [num(r, "k_C2_per_s") for r in rates],
              "total": [num(r, "k_total_per_s") for r in rates]}
    temps = [num(r, "temperature_K") for r in rates]
    fit_ref = {r["quantity"].lower(): r for r in read_ref(test, "derived_arrhenius_fits.csv") if r["n_points"] == "23"}
    fit_ok = len(fit_records) >= 3 and len(temps) == 23
    R = 0.00198720425864
    for q, measured in series.items():
        rec = fit_records.get(q) or fit_records.get("k_" + q + "_full_range")
        if not isinstance(rec, dict): fit_ok = False; continue
        try:
            a = float(rec["A_per_s"]); n = float(rec["n_T_exponent"]); ea = float(rec["Ea_kcal_per_mol"])
            tref = float(rec["T_ref_K"]); lo = float(rec["fit_min_K"]); hi = float(rec["fit_max_K"])
            claimed = float(rec["max_ln_k_deviation"]); points = int(rec["n_points"])
            formula = str(rec["formula"]).lower().replace(" ", "").replace("**", "^")
            fit_ok &= a > 0 and tref > 0 and lo == 200 and hi == 500 and points == 23
            fit_ok &= formula in {"k(t)=a*(t/t_ref_k)^n*exp(-ea_kcal_per_mol/(r*t))",
                                  "k=a*(t/t_ref_k)^n*exp(-ea_kcal_per_mol/(r*t))"}
            predictions = [math.log(a) + n*math.log(t/tref) - ea/(R*t) for t in temps]
            measured_logs = [math.log(x) for x in measured]
            residual = max(abs(x-y) for x,y in zip(predictions, measured_logs))
            gold_fit = fit_ref["k_"+q+"_full_range"]
            target_residual = float(gold_fit["max_ln_k_deviation"])
            fit_ok &= claimed >= residual - 0.001 and abs(claimed - residual) <= 0.01 and abs(residual-target_residual) <= 0.01
            # Compare the submitted curve to the frozen full-range modified-Arrhenius
            # fit pointwise. Gold's documented convention uses T_ref=1e6 K.
            ga, gn, gea = (float(gold_fit[k]) for k in ("A_per_s", "n_T_exponent", "Ea_kcal_per_mol"))
            gold_predictions = [math.log(ga) + gn*math.log(t/1.0e6) - gea/(R*t) for t in temps]
            fit_ok &= max(abs(x-y) for x,y in zip(predictions, gold_predictions)) <= 0.01
        except (KeyError, TypeError, ValueError, OverflowError): fit_ok = False
    result[names[3]] = fit_ok
    reason[names[3]] = "declared modified Arrhenius equation is evaluated at all 23 temperatures; residuals match measured curvature"

    branch = rows(final / "branching_curve.csv")
    check_columns(branch, {"temperature_K", "branching_C1_percent"}, "branching_curve.csv")
    bmap = {round(num(r, "temperature_K"), 6): r for r in branch}
    branch_ok = len(branch) == 23 and len(bmap) == 23 and set(bmap) == {round(t,6) for t in temps}
    for row in rates:
        t = round(num(row, "temperature_K"), 6)
        if t not in bmap: branch_ok = False; continue
        expected_pct = 100*num(row,"k_C1_per_s")/(num(row,"k_C1_per_s")+num(row,"k_C2_per_s"))
        branch_ok &= near(num(bmap[t], "branching_C1_percent"), expected_pct, 0.01)
    branch_ok &= near(num(bmap[300.0], "branching_C1_percent"), 21.907, 0.5) if 300.0 in bmap else False
    notes = text(final / "derivation_notes.md")
    notes_l = notes.lower()
    has_300 = any(s in notes_l for s in ("300 k", "300k"))
    has_range = any(s in notes_l for s in ("12.8", "12.9")) and any(s in notes_l for s in ("31.0", "31.1"))
    branch_ok &= has_300 and has_range and any(s in notes_l for s in ("temperature-dependent", "varies with temperature", "随温度"))
    result[names[4]] = branch_ok
    reason[names[4]] = "branching fractions recomputed at every row, including the bounded 300 K statement and temperature range"
    pressure_ok = len(rates) == 23 and all(near(num(r,"pressure_Torr"),760,1e-8) and r["bath_gas"].upper()=="N2" for r in rates)
    pressure_ok &= any(s in notes_l for s in ("cannot infer pressure", "cannot be inferred", "single pressure", "single-pressure", "单压不能", "不能推断压力"))
    result[names[5]] = pressure_ok
    reason[names[5]] = "all rows state 760 Torr/N2 and notes state this grid cannot establish pressure response"
    return [criterion(n, result[n], reason[n], level) for n, level in zip(names, ("L1","L2","L3","L3","L3","L3"))]


def case05(app: Path, final: Path, test: Path) -> list[dict]:
    ref = read_ref(test, "mesmer_figure4_rates.csv")
    published = read_ref(test, "SD_figure4_rates.csv")
    matrix = rows(final / "bpr_rate_matrix.csv")
    check_columns(matrix, {"molecule", "oh_addition_site", "source_file", "temperature_K", "pressure_Torr", "bath_gas", "k_channel1_per_s", "k_channel2_per_s", "k_dominant_per_s"}, "bpr_rate_matrix.csv")
    exp = {Path(r["file"]).name: r for r in ref}
    got = {Path(pick(r, "source_file")).name: r for r in matrix}
    provenance = len(got) == 15 and len(matrix) == 15 and set(got) == set(exp)
    for file, e in exp.items():
        r = got.get(file, {})
        try:
            rel=Path(str(r["source_file"]))
            if rel.is_absolute() or ".." in rel.parts: provenance=False; continue
            if rel.parts and rel.parts[0]=="assets": rel=Path(*rel.parts[1:])
            native=app/"assets"/rel
            matches=list((app/"assets").rglob(file))
            if len(matches)!=1 or native.resolve()!=matches[0].resolve() or native.is_symlink(): provenance=False;continue
            root=ET.parse(native).getroot(); ns={"me":"http://www.chem.leeds.ac.uk/mesmer"}
            pt=root.find(".//me:PTpair",ns); rate=root.find(".//me:analysis/me:rateList",ns)
            if pt is None or rate is None: provenance=False;continue
            entries={x.attrib.get("toRef"):x for x in rate.findall("me:firstOrderRate",ns)}
            k1=float(entries["ringopen-prod1"].text);k2=float(entries["ringopen-prod2"].text)
            provenance &= rate.attrib.get("units")=="s-1" and len(entries)==2
            provenance &= r["molecule"].lower() == e["molecule"].lower() and r["oh_addition_site"].lower() == e["oh_addition_site"].lower()
            provenance &= near(num(r,"temperature_K"),float(pt.attrib["T"]),1e-8) and near(float(e["temperature_K"]),float(pt.attrib["T"]),1e-8)
            provenance &= near(num(r,"pressure_Torr"),float(pt.attrib["P"]),1e-8) and near(num(r,"pressure_Torr"),760,1e-8)
            provenance &= r["bath_gas"].upper()==pt.attrib.get("bathGas","").upper()=="N2"
            provenance &= near(num(r,"k_channel1_per_s"),k1,1e-4,rel=True) and near(num(r,"k_channel2_per_s"),k2,1e-4,rel=True)
            provenance &= near(num(r,"k_dominant_per_s"),max(k1,k2),1e-4,rel=True)
        except (CandidateFault, OSError, ET.ParseError, KeyError, ValueError, TypeError): provenance = False
    reconciliation = rows(final / "cell_reconciliation.csv")
    check_columns(reconciliation, {"molecule", "oh_addition_site", "published_value_per_s", "source_file", "temperature_K", "matched_definition", "matched_value_per_s", "relative_deviation", "reconciled"}, "cell_reconciliation.csv")
    rec_map={(r["molecule"].lower(),r["oh_addition_site"].lower()):r for r in reconciliation}
    pub_map={(r["molecule"].lower(),r["oh_addition_site"].lower()):r for r in published}
    native_map={(r["molecule"].lower(),r["oh_addition_site"].lower()):r for r in matrix}
    rec_ok=len(reconciliation)==len(rec_map)==len(pub_map)==16 and set(rec_map)==set(pub_map)
    bad_expected = {("benzene", "ipso"), ("ethylbenzene", "ipso"), ("m-xylene", "meta"), ("p-xylene", "ipso"), ("toluene", "meta"), ("m-xylene","ortho")}
    for key,pub in pub_map.items():
        row=rec_map.get(key,{})
        try:
            published_rate=float(pub["k_298_per_s"])
            rec_ok &= near(num(row,"published_value_per_s"),published_rate,max(1e-14,published_rate*1e-8))
            native=native_map.get(key)
            if native is None:
                rec_ok &= key==("m-xylene","ortho") and row["matched_definition"].lower()=="missing_native" and not row["source_file"].strip() and not row["temperature_K"].strip() and not row["matched_value_per_s"].strip() and not row["relative_deviation"].strip() and row["reconciled"].lower() in {"false","no","unreconciled"}
                continue
            rec_ok &= Path(row["source_file"]).name==Path(native["source_file"]).name and near(num(row,"temperature_K"),num(native,"temperature_K"),1e-8)
            vals={"channel1":num(native,"k_channel1_per_s"),"channel2":num(native,"k_channel2_per_s"),"faster":max(num(native,"k_channel1_per_s"),num(native,"k_channel2_per_s")),"sum":num(native,"k_channel1_per_s")+num(native,"k_channel2_per_s")}
            definition=row["matched_definition"].lower().replace(" ","")
            aliases={"channel1":"channel1","channel 1":"channel1","channel_prod1":"channel1","channel2":"channel2","channel 2":"channel2","channel_prod2":"channel2","faster":"faster","max":"faster","max_channel":"faster","sum":"sum"}
            canonical=aliases.get(definition)
            rec_ok &= canonical is not None
            if canonical is None: continue
            matched=vals[canonical]; rel=abs(matched-published_rate)/published_rate
            rec_ok &= near(num(row,"matched_value_per_s"),matched,max(1e-14,matched*1e-6))
            rec_ok &= near(num(row,"relative_deviation"),rel,1e-5)
            best_rel=min(abs(v-published_rate)/published_rate for v in vals.values())
            expected_yes=best_rel<=0.05
            got_yes=row["reconciled"].lower() in {"true","yes","reconciled"}
            rec_ok &= got_yes==expected_yes
            if got_yes: rec_ok &= rel<=0.05
        except (CandidateFault,KeyError,ValueError,ZeroDivisionError): rec_ok=False
    unreconciled={(r["molecule"].lower(),r["oh_addition_site"].lower()) for r in reconciliation if r["reconciled"].lower() in {"false","no","unreconciled"}}
    unreconciled_ok=unreconciled==bad_expected and sum(1 for r in reconciliation if r["reconciled"].lower() in {"true","yes","reconciled"})==10
    anomalies = json_obj(final / "anomalies.json")
    anomaly_entries=anomalies.get("unreconciled",[]) if isinstance(anomalies,dict) else []
    anomaly_map={(str(x.get("molecule","")).lower(),str(x.get("site","")).lower()):x for x in anomaly_entries if isinstance(x,dict)}
    anomaly_ok=len(anomaly_entries)==len(anomaly_map)==6 and set(anomaly_map)==bad_expected
    for key in bad_expected:
        e=anomaly_map.get(key,{})
        row=rec_map.get(key,{})
        anomaly_ok &= bool(e.get("reason"))
        anomaly_ok &= near(float(e.get("published_value_per_s","nan")),num(row,"published_value_per_s"),max(1e-14,num(row,"published_value_per_s")*1e-8))
        native=native_map.get(key)
        if native is None:
            anomaly_ok &= not e.get("candidates") and not e.get("source_file") and e.get("temperature_K") in (None,"") and "no deposited native" in str(e.get("reason","")).lower()
            continue
        anomaly_ok &= Path(str(e.get("source_file",""))).name==Path(native["source_file"]).name and near(float(e.get("temperature_K","nan")),num(native,"temperature_K"),1e-8)
        expected_candidates={"channel1":num(native,"k_channel1_per_s"),"channel2":num(native,"k_channel2_per_s"),"faster":max(num(native,"k_channel1_per_s"),num(native,"k_channel2_per_s")),"sum":num(native,"k_channel1_per_s")+num(native,"k_channel2_per_s")}
        got={str(c.get("definition","")).lower().replace(" ",""):c for c in e.get("candidates",[]) if isinstance(c,dict)}
        anomaly_ok &= {"channel1","channel2","faster","sum"} <= set(got)
        for definition,value in expected_candidates.items():
            c=got.get(definition,{})
            anomaly_ok &= near(float(c.get("value_per_s","nan")),value,max(1e-14,value*1e-6))
            pubval=num(row,"published_value_per_s")
            anomaly_ok &= near(float(c.get("relative_deviation","nan")),abs(value-pubval)/pubval,1e-5)
    trend = text(final / "trend_analysis.md")
    trend_evidence=json_obj(final/"trend_evidence.json")
    single_claim_ok=isinstance(trend_evidence,dict) and trend_evidence.get("single_definition_claim") is False
    scope=trend_evidence.get("temperature_scope",{}) if isinstance(trend_evidence,dict) else {}
    recorded=scope.get("recorded_temperatures_K",[])
    temp_ok=len(recorded)==3 and all(any(near(float(x),t,0.005) for x in recorded) for t in (298,298.15,300))
    temp_ok &= scope.get("normalisation_status")=="indeterminate_without_molecule_specific_temperature_coefficients"
    arange=scope.get("toluene_ipso_298_to_300_activation_percent_range",[]); nrange=scope.get("with_n_percent",[])
    temp_ok &= len(arange)==2 and near(float(arange[0]),21.7,0.15) and near(float(arange[1]),22.8,0.15)
    temp_ok &= len(nrange)==2 and near(float(nrange[0]),23,0.5) and near(float(nrange[1]),24,0.5)
    temp_ok &= scope.get("close_orderings_indeterminate") is True
    temp_ok &= any(x in trend for x in ("temperature", "温度")) and any(x in trend for x in ("cannot", "indeterminate", "不确定", "无法"))
    count_reconciled = sum(1 for r in reconciliation if r["reconciled"].lower() in {"true", "yes", "reconciled"})
    count_ok = count_reconciled == 10
    return [
        criterion("matrix_and_reconciliation_present", len(matrix) == 15 and len(reconciliation) == 16, "15 native outputs and 16 published cells supplied", "L1"),
        criterion("provenance_per_cell", provenance, "source files, temperatures, and both MESMER channels match the frozen native-output register", "L2"),
        criterion("reconcilable_cells_reproduced", count_ok and rec_ok, "all 16 published values map to a native definition or the explicit missing-witness state; values and residuals recomputed", "L3"),
        criterion("irreconcilable_cells_disclosed", unreconciled_ok and anomaly_ok, "five measured conflicts are named with candidate values and residuals", "L3"),
        criterion("single_definition_claim_rejected", anomaly_ok and single_claim_ok, "structured evidence rejects a universal single-definition claim", "L3"),
        criterion("temperature_normalisation_before_trend", temp_ok, "recorded temperatures and the limited toluene sensitivity example are stated", "L3"),
    ]


def case06(app: Path, final: Path, test: Path) -> list[dict]:
    """Recompute the 30 deposited energy candidates from the public native files."""
    ref = read_ref(test, "derived_rono2_si_table9.csv")
    conflict = read_ref(test, "rono2_meta_alkoxy_identity_conflict.csv")
    si = read_ref(test, "SI_table9_organonitrate.csv")
    expected_cells = {(r["species_column"], r["quantity"]) for r in ref}
    published = {(r["species_column"], r["quantity"]): r for r in si if r.get("unit") == "kcal/mol"}
    def candidate_rows(name: str) -> list[dict[str,str]]:
        try:return rows(final / name)
        except CandidateFault:return []
    candidate = candidate_rows("rono2_energies.csv")
    cand_cols = {"species_column", "quantity", "file_stem", "species_file", "anchor_file", "source_dft_file", "source_f12_file", "anchor_dft_file", "anchor_f12_file", "includes_no2", "dft_zero_point_kcal_per_mol", "composite_kcal_per_mol", "published_kcal_per_mol", "deviation"}
    main_schema=bool(candidate) and cand_cols<=set(candidate[0])
    all_candidates = candidate_rows("rono2_candidates.csv")
    candidate_schema=bool(all_candidates) and cand_cols<=set(all_candidates[0])
    mainmap = {(r["species_column"],r["quantity"]):r for r in candidate}
    candmap = {(r["species_column"],r["quantity"],r["file_stem"]):r for r in all_candidates}
    safe = True
    native_calc: dict[tuple[str,str,str],dict] = {}
    dirs = {"benzene":"RONO2/Benzene", "toluene-ipso":"RONO2/Toluene/Ipso", "toluene-ortho":"RONO2/Toluene/Ortho", "toluene-meta":"RONO2/Toluene/Meta", "toluene-para":"RONO2/Toluene/Para"}
    def native_path(value: str) -> Path:
        rel=Path(value.replace("\\","/"))
        if rel.is_absolute() or ".." in rel.parts: raise CandidateFault("unsafe submitted asset path")
        parts=list(rel.parts)
        if parts and parts[0]=="assets":parts=parts[1:]
        path=app/"assets"/Path(*parts)
        if path.is_symlink() or not path.is_file() or (app/"assets").resolve() not in path.resolve().parents: raise CandidateFault("submitted native path is not a regular public asset")
        return path
    def last_float(pattern: str, raw: str) -> float:
        found=re.findall(pattern,raw,re.M)
        if not found: raise ValueError("native energy label missing")
        return float(found[-1])
    def gaussian_values(path: Path) -> tuple[float,float]:
        raw=path.read_text(encoding="utf-8",errors="replace")
        return last_float(r"Zero-point correction=\s*(-?\d+\.\d+)",raw),last_float(r"Sum of electronic and zero-point Energies=\s*(-?\d+\.\d+)",raw)
    def f12_value(path: Path) -> float:
        raw=path.read_text(encoding="utf-8",errors="replace")
        try:return last_float(r"RCCSD\(T\)-F12A/cc-pVDZ-F12 energy=\s*(-?\d+\.\d+)",raw)
        except ValueError:return last_float(r"!RHF-RCCSD\(T\)-F12a energy\s+(-?\d+\.\d+)",raw)
    no2_d=app/"assets/RONO2/NOx/NO2-DFT.log"; no2_f=app/"assets/RONO2/NOx/NO2-F12.out"
    no2_zpe,no2_e0=gaussian_values(no2_d); no2_e=f12_value(no2_f)
    identity_ok=False
    identity={}
    try:
        identity=conflict[0]
        d1=native_path("assets/"+normalized_path(identity["dft_path"]));d2=native_path("assets/"+normalized_path(conflict[1]["dft_path"]))
        f1=native_path("assets/"+normalized_path(identity["f12_path"]));f2=native_path("assets/"+normalized_path(conflict[1]["f12_path"]))
        identity_ok=sha(d1)==sha(d2)==identity["dft_sha256"] and sha(f1)==sha(f2)==identity["f12_sha256"]
    except (CandidateFault,KeyError,IndexError,OSError):identity_ok=False
    for e in ref:
        col,qty,stem=e["species_column"],e["quantity"],e["file_stem"]
        folder=dirs[col]
        dft_rel=f"{folder}/{stem}-DFT.log";f12_rel=f"{folder}/{stem}-F12.out"
        anchor_d_rel=f"{folder}/B-RONO2-DFT.log";anchor_f_rel=f"{folder}/B-RONO2-F12.out"
        no2="+ NO2" in qty
        try:
            dft=native_path("assets/"+dft_rel);f12=native_path("assets/"+f12_rel);ad=native_path("assets/"+anchor_d_rel);af=native_path("assets/"+anchor_f_rel)
            z,e0=gaussian_values(dft);az,ae0=gaussian_values(ad);ef=f12_value(f12);aef=f12_value(af)
            dft_rel_value=((e0+(no2_e0 if no2 else 0))-ae0)*HARTREE_KCAL
            composite=((ef+(no2_e if no2 else 0)-aef)+(z+(no2_zpe if no2 else 0)-az))*HARTREE_KCAL
            pub=float(published[(col,qty)]["value"])
            native_calc[(col,qty,stem)]={"dft":dft_rel_value,"composite":composite,"published":pub,"deviation":abs(composite-pub),"no2":no2,"dft_path":dft_rel,"f12_path":f12_rel,"anchor_d":anchor_d_rel,"anchor_f":anchor_f_rel}
        except (CandidateFault,OSError,ValueError,KeyError,TypeError):safe=False
    def numerical_table_check(rows_in: list[dict], is_main: bool) -> bool:
        ok=True
        exp_keys={(r["species_column"],r["quantity"],r["file_stem"]) for r in ref}
        got_keys={(r.get("species_column",""),r.get("quantity",""),r.get("file_stem","")) for r in rows_in}
        if is_main:
            ok &= len(rows_in)==20 and len(got_keys)==20 and got_keys<=exp_keys
        else:
            ok &= len(rows_in)==len(got_keys)==len(exp_keys) and got_keys==exp_keys
        if is_main:
            cells={(r.get("species_column",""),r.get("quantity","")) for r in rows_in}
            ok &= len(rows_in)==20 and cells==expected_cells
        for r in rows_in:
            key=(r.get("species_column",""),r.get("quantity",""),r.get("file_stem",""));calc=native_calc.get(key)
            if calc is None:ok=False;continue
            expected_paths={"species_file":"assets/"+calc["dft_path"],"anchor_file":"assets/"+calc["anchor_d"],"source_dft_file":calc["dft_path"],"source_f12_file":calc["f12_path"],"anchor_dft_file":calc["anchor_d"],"anchor_f12_file":calc["anchor_f"]}
            for field,value in expected_paths.items():
                try:ok &= normalized_path(r[field])==normalized_path(value)
                except (KeyError,TypeError):ok=False
            try:
                ok &= near(num(r,"dft_zero_point_kcal_per_mol"),calc["dft"],0.002)
                ok &= near(num(r,"composite_kcal_per_mol"),calc["composite"],0.002)
                ok &= near(num(r,"published_kcal_per_mol"),calc["published"],0.001)
                ok &= near(num(r,"deviation"),calc["deviation"],0.002)
                ok &= r.get("includes_no2","").lower() in {"true","yes","1"} if calc["no2"] else r.get("includes_no2","").lower() in {"false","no","0"}
            except (CandidateFault,KeyError,TypeError):ok=False
        return bool(ok)
    all_native_rows_ok=safe and candidate_schema and numerical_table_check(all_candidates,False)
    main_native_ok=safe and main_schema and numerical_table_check(candidate,True)
    valid_cells=[]
    for key in expected_cells:
        possible=[native_calc.get((key[0],key[1],r["file_stem"])) for r in ref if (r["species_column"],r["quantity"])==key]
        possible=[x for x in possible if x]
        if possible: valid_cells.append((key,min(x["deviation"] for x in possible)))
    comparable=[(k,d) for k,d in valid_cells if k!=("toluene-meta","x-B-RO + NO2")]
    energy_rows_ok=len(comparable)==19 and all(d<=0.10+1e-9 for _,d in comparable)
    selected_keys={(r.get("species_column",""),r.get("quantity","")):r for r in candidate}
    selected_devs=[]
    for key in expected_cells:
        r=selected_keys.get(key,{})
        try:
            actual=float(r["deviation"]); selected_devs.append((key,actual))
            if key!=("toluene-meta","x-B-RO + NO2"):energy_rows_ok &= actual<=0.10+1e-9
        except (KeyError,TypeError,ValueError):energy_rows_ok=False
    energy_rows_ok &= len(selected_devs)==20
    no2_rows=[r for r in all_candidates if "+ NO2" in r.get("quantity","")]
    no2_main=[r for r in candidate if "+ NO2" in r.get("quantity","")]
    no2_ok=len(no2_rows)==13 and len(no2_main)==10 and all(native_calc.get((r.get("species_column"),r.get("quantity"),r.get("file_stem")),{}).get("no2") and r.get("includes_no2","").lower() in {"true","yes","1"} for r in no2_rows)
    ipso=native_calc.get(("toluene-ipso","x-B-RO + NO2","B-RO"),{})
    no2_ok &= near(ipso.get("composite",float("nan")),40.484,0.01) and near(ipso.get("published",float("nan")),40.5,0.1)
    identity_meta=native_calc.get(("toluene-meta","x-B-RO + NO2","B-RO"),{})
    ident_report=any(r.get("species_column")=="toluene-meta" and r.get("quantity")=="x-B-RO + NO2" and r.get("file_stem")=="B-RO" for r in candidate)
    try:identity_sub=json_obj(final/"identity_conflict.json")
    except CandidateFault:identity_sub={}
    identity_items=identity_sub.get("advertised_species",[]) if isinstance(identity_sub,dict) else []
    identity_map={x.get("label"):x for x in identity_items if isinstance(x,dict)}
    identity_submission_ok=len(identity_items)==2 and set(identity_map)=={"B-RO","RB-C1-RO"} and identity_sub.get("includes_no2") is True and identity_sub.get("status")=="unrecoverable_input_identity_collision"
    for label,stem in (("B-RO","B-RO"),("RB-C1-RO","RB-C1-RO")):
        evidence=identity_map.get(label,{})
        for typ,suffix in (("dft","DFT.log"),("f12","F12.out")):
            rel=f"RONO2/Toluene/Meta/{stem}-{suffix}"
            try:
                native=native_path("assets/"+rel)
                identity_submission_ok &= normalized_path(evidence[f"{typ}_file"])==rel and evidence[f"{typ}_sha256"]==sha(native)
                if typ=="f12":
                    raw=native.read_text(encoding="utf-8",errors="replace")
                    matches=re.findall(r"geometry=\{\s*\n\s*\d+\s*\n\s*(\S+?\.log),Energy:",raw)
                    identity_submission_ok &= bool(matches) and evidence.get("f12_source_log_name")==matches[-1]
                    identity_submission_ok &= near(float(evidence["f12_energy_au"]),f12_value(native),1e-8)
            except (CandidateFault,KeyError,TypeError,ValueError,OSError):identity_submission_ok=False
    identity_submission_ok &= identity_map.get("B-RO",{}).get("dft_sha256")==identity_map.get("RB-C1-RO",{}).get("dft_sha256") and identity_map.get("B-RO",{}).get("f12_sha256")==identity_map.get("RB-C1-RO",{}).get("f12_sha256")
    identity_submission_ok &= near(float(identity_sub.get("computed_with_free_no2_kcal_per_mol","nan")),identity_meta.get("composite",float("nan")),0.002) and near(float(identity_sub.get("published_kcal_per_mol","nan")),38.4,0.001) and near(float(identity_sub.get("abs_deviation_kcal_per_mol","nan")),identity_meta.get("deviation",float("nan")),0.002)
    try:disc=text(final/"discrepancies.md")
    except CandidateFault:disc=""
    conflict_prose=all(x in disc.lower() for x in ("b-ro","rb-c1-ro","no2")) and any(x in disc.lower() for x in ("unrecoverable","unresolved","cannot be repaired","无法恢复","不可恢复","冲突"))
    conflict_ok=identity_ok and identity_submission_ok and ident_report and conflict_prose and near(identity_meta.get("composite",float("nan")),-6.6167,0.002) and near(identity_meta.get("published",float("nan")),38.4,0.001) and near(identity_meta.get("deviation",float("nan")),45.0167,0.002)
    try:unverified=json_obj(final/"unverified_rows.json")
    except CandidateFault:unverified={}
    unrows=unverified.get("rows",[]) if isinstance(unverified,dict) else []
    unverified_energy={(r.get("species_column"),r.get("quantity")) for r in unrows if r.get("status")=="unverified_input_identity_conflict"}
    rate_entries=[r for r in unrows if str(r.get("quantity","" )).startswith("kx-")]
    rate_keys={(r.get("species_column"),r.get("quantity")) for r in rate_entries}
    rate_ref={(r["species_column"],r["quantity"]) for r in si if str(r.get("quantity","")).startswith("kx-")}
    rate_values_ok=len(rate_entries)==10 and rate_keys==rate_ref
    rate_ref_values={(r["species_column"],r["quantity"]):float(r["value"]) for r in si if str(r.get("quantity","")).startswith("kx-")}
    for r in rate_entries:
        key=(r.get("species_column"),r.get("quantity"))
        try:rate_values_ok &= near(float(r["published_rate_per_s"]),rate_ref_values[key],max(1e-300,abs(rate_ref_values[key])*0.002))
        except (KeyError,TypeError,ValueError):rate_values_ok=False
    unsupported_ok=rate_values_ok and all(r.get("status")=="unsupported_no_native_witness" and "no corresponding native MESMER" in r.get("reason","") for r in rate_entries)
    unsupported_ok &= unverified_energy=={("toluene-meta","x-B-RO + NO2")} and any("identical" in r.get("reason","").lower() for r in unrows if r.get("status")=="unverified_input_identity_conflict")
    try:assignment=json_obj(final/"column_assignment.json")
    except CandidateFault:assignment={}
    life=assignment.get("lifetime_evidence",[]) if isinstance(assignment,dict) else []
    life_map={r.get("species_column"):r for r in life if isinstance(r,dict)}
    assignment_ok=len(assignment.get("columns",[]))==5 and {r.get("species_column"):r.get("assigned_column") for r in assignment.get("columns",[]) if isinstance(r,dict)}=={c:c for c in dirs}
    for col,rate,minutes in (("benzene",4.9e-4,34.0),("toluene-meta",6e-4,27.8),("toluene-para",1e-4,166.7)):
        r=life_map.get(col,{})
        try:
            assignment_ok &= near(float(r["published_rate_per_s"]),rate,rate*0.001) and near(float(r["lifetime_minutes"]),minutes,0.25) and near(1/(float(r["published_rate_per_s"])*60),float(r["lifetime_minutes"]),0.25) and r.get("assigned_column")==col
        except (KeyError,TypeError,ValueError,ZeroDivisionError):assignment_ok=False
    assignment_ok &= len(life)==3 and "not native MESMER witnesses" in assignment.get("rate_witness_scope","")
    rule=assignment.get("comparison_rule",{}) if isinstance(assignment,dict) else {}
    band_ok=isinstance(rule,dict) and near(float(rule.get("comparison_tolerance_kcal_per_mol","nan")),0.10,1e-9) and near(float(rule.get("context_tolerance_kcal_per_mol","nan")),0.5,1e-9) and "background" in str(rule.get("context_role","")).lower() and energy_rows_ok
    channel_records=assignment.get("channel_selection",[]) if isinstance(assignment,dict) else []
    channel_map={x.get("species_column"):x for x in channel_records if isinstance(x,dict)}
    channel_selection_ok=len(channel_records)==5 and set(channel_map)==set(dirs)
    for col in dirs:
        group=[r for r in all_candidates if r.get("species_column")==col and r.get("quantity")=="TSrearrangement"]
        record=channel_map.get(col,{})
        submitted={x.get("file_stem"):x for x in record.get("candidates",[]) if isinstance(x,dict)}
        expected_stems={r["file_stem"] for r in ref if r["species_column"]==col and r["quantity"]=="TSrearrangement"}
        channel_selection_ok &= set(submitted)==expected_stems=={r.get("file_stem") for r in group}
        mainrow=mainmap.get((col,"TSrearrangement"),{})
        channel_selection_ok &= record.get("selected_file_stem")==mainrow.get("file_stem")
        within=[]
        for row in group:
            stem=row.get("file_stem");calc=native_calc.get((col,"TSrearrangement",stem),{});cr=submitted.get(stem,{})
            try:
                channel_selection_ok &= near(float(cr["composite_kcal_per_mol"]),calc["composite"],0.002) and near(float(cr["published_kcal_per_mol"]),calc["published"],0.001) and near(float(cr["abs_deviation"]),calc["deviation"],0.002)
                if calc["deviation"]<=0.10:within.append(stem)
            except (KeyError,TypeError,ValueError):channel_selection_ok=False
        channel_selection_ok &= record.get("ambiguous") is (len(within)>1)
    ts=[native_calc.get(("toluene-ortho","TSrearrangement",stem),{}) for stem in ("TS-C1","TS-C2")]
    ambiguity_ok=len(ts)==2 and near(ts[0].get("composite",float("nan")),25.563,0.002) and near(ts[1].get("composite",float("nan")),25.408,0.002) and all(x.get("deviation",99)<=0.10 for x in ts) and near(abs(ts[0]["deviation"]-ts[1]["deviation"]),0.029,0.003) and abs(ts[0]["composite"]-ts[1]["composite"])>0.10
    ambiguity_ok &= channel_selection_ok and all(w in disc for w in ("25.563","25.408")) and ("difference between their deviations" in disc or "偏差" in disc)
    ambiguity_ok &= all(any(r.get("species_column")=="toluene-ortho" and r.get("quantity")=="TSrearrangement" and r.get("file_stem")==stem for r in all_candidates) for stem in ("TS-C1","TS-C2"))
    band_ok &= energy_rows_ok
    return [
        criterion("energy_face_complete", len(candidate)==20 and len(mainmap)==20 and len(all_candidates)==30 and len(candmap)==30 and main_native_ok and all_native_rows_ok and assignment_ok and unsupported_ok, "20 unique energy cells and all 30 native candidates are parsed; assignment and unsupported rows are structured", "L1"),
        criterion("no2_fragment_accounting_correct", no2_ok and all_native_rows_ok, "13 NO2-containing candidates across 10 cells include native free-NO2 F12 and ZPE contributions", "L2"),
        criterion("published_energy_rows_reproduced", energy_rows_ok and main_native_ok and band_ok, "19 of 20 comparable cells reproduce within 0.10 kcal/mol, using native recomputation and the SI DOCX values", "L3"),
        criterion("meta_alkoxy_source_identity_conflict_reported", conflict_ok and unsupported_ok, "paired deposited DFT/F12 inputs are byte-identical and the computed discrepancy is disclosed", "L3"),
        criterion("column_assignment_decoded", assignment_ok, "SI lifetime evidence maps benzene, meta and para columns; SI rates are not treated as native witnesses", "L3"),
        criterion("channel_selection_among_two_saddles", ambiguity_ok and channel_selection_ok, "both ortho TS candidates and their distinct energies/deviations are reported; no unique channel is asserted", "L3"),
        criterion("unsupported_rate_rows_declared", unsupported_ok, "both SI rate rows across all five species columns are explicitly unverified", "L3"),
    ]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--app-dir", type=Path, required=True)
    p.add_argument("--tests-dir", type=Path, required=True)
    p.add_argument("--final-dir", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    report: dict = {"status": "ENV_INVALID", "reward": None, "checks": [], "failures": []}
    try:
        refs = json.loads((args.tests_dir / "refs.json").read_text(encoding="utf-8"))
        case_id = refs["case_id"]
        if case_id != PINNED_CASE_ID or refs.get("asset_hashes") != PINNED_ASSET_REFS:
            raise EnvironmentFault("grader refs.json does not match connector-pinned source refs")
        for rel, expected in PINNED_ASSET_REFS.items():
            path = args.app_dir / rel
            if not regular_file(path, args.app_dir/"assets") or sha(path) != expected:
                raise EnvironmentFault(f"public input missing or changed: {rel}")
        for table in PINNED_REFERENCES:
            read_ref(args.tests_dir, table)
    except EnvironmentFault as e:
        report["reason"] = str(e)
        report["status"] = "ENV_INVALID"
        report["reward"] = None
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        report["reason"] = f"invalid grader refs/preflight: {type(e).__name__}: {e}"
        report["status"] = "ENV_INVALID"
        report["reward"] = None
    else:
      try:
        if case_id.startswith("case-01-"): checks = case01(args.app_dir, args.final_dir, args.tests_dir)
        elif case_id.startswith("case-02-"): checks = case02(args.app_dir, args.final_dir, args.tests_dir)
        elif case_id.startswith("case-03-"): checks = case03(args.app_dir, args.final_dir, args.tests_dir)
        elif case_id.startswith("case-05-"): checks = case05(args.app_dir, args.final_dir, args.tests_dir)
        elif case_id.startswith("case-06-"): checks = case06(args.app_dir, args.final_dir, args.tests_dir)
        else: raise EnvironmentFault(f"unsupported case id {case_id}")
        report.update(case_id=case_id, checks=checks,
                      failures=[c["name"] for c in checks if not c["passed"]])
        report.update(status="PASS" if not report["failures"] else "FAIL",
                      reward=1 if not report["failures"] else 0)
      except EnvironmentFault as e:
        report["reason"] = str(e)
        report["status"] = "ENV_INVALID"
        report["reward"] = None
      except CandidateFault as e:
        report["reason"] = str(e)
        report["status"] = "FAIL"
        report["reward"] = 0
        report["failures"].append("candidate_output_invalid")
      except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError, OSError, UnicodeError, csv.Error) as e:
        # Output parsing errors are candidate failures. Reference/input faults are preflighted above.
        report["reason"] = f"{type(e).__name__}: {e}"
        report["status"] = "FAIL"
        report["reward"] = 0
        report["failures"].append("candidate_output_invalid")
    if report["status"] == "FAIL" and not report["checks"]:
        report["checks"] = [criterion(name,False,"Candidate output invalid: "+report.get("reason",""),level) for name,level in EXPECTED_CRITERIA]
        report["failures"] = [name for name,_ in EXPECTED_CRITERIA] + report["failures"]
    report["verifier_sha256"] = sha(Path(__file__))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return {"PASS": 0, "FAIL": 1}.get(report["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
