// Scratch export, run from app/ but kept outside the app tree (plan v4 R2/R3): the resolved holder tree of each
// offered catalogue row, by the app's own parser, checked against the app's own filing destinations.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:pantry/appliance/catalogue_sheet.dart';
import 'package:pantry/appliance/front_nodes.dart';

String r(double v) => v.toStringAsFixed(4);

void main() {
  test('export layouts', () {
    final sheet = parseCatalogueSheet(File('assets/catalogue/fronts.json').readAsStringSync());
    bool offered(String k) => k.startsWith('template:') || (k.startsWith('model:') && !k.startsWith('model:us-'));
    final rows = <Map<String, Object?>>[];
    for (final f in sheet.fronts.where((f) => offered(f.key))) {
      final row = {
        'key': f.key,
        'version': f.version,
        'brand': f.brand,
        'model': f.model,
        'typical': f.typical,
        'source': f.source,
        'name': {'ko': f.defaultName.ko, 'en': f.defaultName.en},
        'mm': [f.widthMm, f.heightMm, f.depthMm],
        'compartments': [
          for (final c in f.compartments)
            {
              'id': c.id,
              'name': {'ko': c.name.ko, 'en': c.name.en},
              'kind': c.kind.name,
              'box_mm': [c.box.x, c.box.y, c.box.z, c.box.w, c.box.h, c.box.d],
              'levels': [
                for (final (i, l) in c.levels.indexed)
                  {'id': '${c.id}/L$i', 'kind': l.kind.name, 'top': l.top, 'floor': l.floor, 'label': l.label},
              ],
            },
        ],
        'panels': [
          for (final p in f.panels)
            if (p.pockets.isNotEmpty)
              {
                'id': p.id,
                'opens': p.opens,
                'rect': [p.rect.u, p.rect.v, p.rect.w, p.rect.h],
                'pockets': [
                  for (final q in p.pockets)
                    {'id': '${p.id}/${q.id}', 'bottom': q.bottomFrac, 'height': q.heightFrac, 'u': q.u, 'w': q.w},
                ],
              },
        ],
      };
      // Parity: the holders in the export are exactly the app's filing destinations for this row (semantic role
      // paths, not the fresh node ids).
      final nodes = nodesForFront(f, 'root', 'x');
      final byId = {for (final n in nodes) n.id: n};
      final app = <String>[];
      final levelIndex = <String, int>{};
      for (final n in nodes.skip(1)) {
        final s = n.spec!;
        final parent = byId[n.parentId]!.spec!;
        if (s.startsWith('comp=')) {
          app.add('compartment ${s.split(';').first.substring(5)}');
        } else if (s.startsWith('level:')) {
          final comp = parent.split(';').first.substring(5);
          final i = levelIndex[comp] = (levelIndex[comp] ?? -1) + 1;
          app.add('level $comp/L$i ${s.split(';').first.substring(6)}');
        } else if (s.startsWith('pocket=') && !s.contains('/')) {
          app.add('panel ${s.substring(7)}');
        } else if (s.startsWith('pocket=')) {
          app.add('pocket ${s.split(';').first.substring(7)}');
        } else {
          fail('unexpected holder $s in ${f.key}');
        }
      }
      final ours = <String>[
        for (final c in row['compartments'] as List) ...[
          'compartment ${(c as Map)['id']}',
          for (final l in c['levels'] as List) 'level ${(l as Map)['id']} ${l['kind']}',
        ],
        for (final p in row['panels'] as List) ...[
          'panel ${(p as Map)['id']}',
          for (final q in p['pockets'] as List) 'pocket ${(q as Map)['id']}',
        ],
      ];
      expect(ours, app, reason: f.key);
      rows.add(row);
    }
    expect(rows.any((r) => (r['panels'] as List).where((p) => ((p as Map)['pockets'] as List).isNotEmpty).length >= 2),
        isTrue, reason: 'a row with pockets on two doors is covered');
    File(Platform.environment['OUT']!).writeAsStringSync('${const JsonEncoder.withIndent(' ').convert(rows)}\n');
  });
}
