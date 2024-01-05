import pytest
import math
import numpy as np
import pandas as pd
import datetime

import PIL

import pixeltable as pt
from pixeltable import exceptions as exc
from pixeltable import catalog
from pixeltable.type_system import \
    StringType, IntType, FloatType, TimestampType, ImageType, VideoType, JsonType, BoolType, ArrayType
from pixeltable.tests.utils import create_test_tbl, assert_resultset_eq, get_video_files
from pixeltable.iterators import FrameIterator


class TestComponentView:
    def test_basic(self, test_client: pt.Client) -> None:
        cl = test_client
        # create video table
        schema = {'video': VideoType(), 'angle': IntType()}
        video_t = cl.create_table('video_tbl', schema)
        video_filepaths = get_video_files()

        # cannot add 'pos' column
        with pytest.raises(exc.Error) as excinfo:
            video_t.add_column(pos=IntType())
        assert 'reserved' in str(excinfo.value)

        # parameter missing
        with pytest.raises(exc.Error) as excinfo:
            args = {'fps': 1}
            _ = cl.create_view('test_view', video_t, iterator_class=FrameIterator, iterator_args=args)
        assert 'missing a required argument' in str(excinfo.value)

        # bad parameter type
        with pytest.raises(exc.Error) as excinfo:
            args = {'video': video_t.video, 'fps': '1'}
            _ = cl.create_view('test_view', video_t, iterator_class=FrameIterator, iterator_args=args)
        assert 'expected int' in str(excinfo.value)

        # bad parameter type
        with pytest.raises(exc.Error) as excinfo:
            args = {'video': 1, 'fps': 1}
            _ = cl.create_view('test_view', video_t, iterator_class=FrameIterator, iterator_args=args)
        assert 'expected file path' in str(excinfo.value)

        # create frame view
        args = {'video': video_t.video, 'fps': 1}
        view_t = cl.create_view('test_view', video_t, iterator_class=FrameIterator, iterator_args=args)
        # computed column that references an unstored computed column from the view and a column from the base
        view_t.add_column(angle2=view_t.angle + 1)
        # computed column that references an unstored and a stored computed view column
        view_t.add_column(v1=view_t.frame.rotate(view_t.angle2), stored=True)
        # computed column that references a stored computed column from the view
        view_t.add_column(v2=view_t.frame_idx - 1)

        # and load data
        rows = [{'video': p, 'angle': 30} for p in video_filepaths]
        video_t.insert(rows)
        # pos and frame_idx are identical
        res = view_t.select(view_t.pos, view_t.frame_idx).collect().to_pandas()
        assert np.all(res['pos'] == res['frame_idx'])

        video_url = video_t.select(video_t.video.fileurl).show(0)[0, 0]
        result = view_t.where(view_t.video == video_url).select(view_t.frame, view_t.frame_idx) \
            .collect()
        result = view_t.where(view_t.video == video_url).select(view_t.frame_idx).order_by(view_t.frame_idx) \
            .collect().to_pandas()
        assert len(result) > 0
        assert np.all(result['frame_idx'] == pd.Series(range(len(result))))

    def test_add_column(self, test_client: pt.Client) -> None:
        cl = test_client
        # create video table
        video_t = cl.create_table('video_tbl', {'video': VideoType()})
        video_filepaths = get_video_files()
        # create frame view
        args = {'video': video_t.video, 'fps': 1}
        view_t = cl.create_view('test_view', video_t, iterator_class=FrameIterator, iterator_args=args)

        rows = [{'video': p} for p in video_filepaths]
        video_t.insert(rows)
        # adding a non-computed column backfills it with nulls
        view_t.add_column(annotation=JsonType(nullable=True))
        assert view_t.count() == view_t.where(view_t.annotation == None).count()
        # adding more data via the base table sets the column values to null
        video_t.insert(rows)
        _ = view_t.where(view_t.annotation == None).count()
        assert view_t.count() == view_t.where(view_t.annotation == None).count()

        with pytest.raises(exc.Error) as excinfo:
            view_t.add_column(annotation=JsonType(nullable=False))
        assert 'must be nullable' in str(excinfo.value)

    def test_update(self, test_client: pt.Client) -> None:
        cl = test_client
        # create video table
        video_t = cl.create_table('video_tbl', {'video': VideoType()})
        # create frame view with manually updated column
        args = {'video': video_t.video, 'fps': 1}
        view_t = cl.create_view(
            'test_view', video_t, schema={'annotation': JsonType(nullable=True)},
            iterator_class=FrameIterator, iterator_args=args)

        video_filepaths = get_video_files()
        rows = [{'video': p} for p in video_filepaths]
        status = video_t.insert(rows)
        assert status.num_excs == 0
        import urllib
        video_url = urllib.parse.urljoin('file:', urllib.request.pathname2url(video_filepaths[0]))
        status = view_t.update({'annotation': {'a': 1}}, where=view_t.video == video_url)
        c1 = view_t.where(view_t.annotation != None).count()
        c2 = view_t.where(view_t.video == video_url).count()
        assert c1 == c2

        with pytest.raises(exc.Error) as excinfo:
            _ = cl.create_view(
                'bad_view', video_t, schema={'annotation': JsonType(nullable=False)},
                iterator_class=FrameIterator, iterator_args=args)
        assert 'must be nullable' in str(excinfo.value)

    def test_chained_views(self, test_client: pt.Client) -> None:
        """Component view followed by a standard view"""
        cl = test_client
        # create video table
        schema = {'video': VideoType(), 'int1': IntType(), 'int2': IntType()}
        video_t = cl.create_table('video_tbl', schema)
        video_filepaths = get_video_files()

        # create first view
        args = {'video': video_t.video, 'fps': 1}
        v1 = cl.create_view('test_view', video_t, iterator_class=FrameIterator, iterator_args=args)
        # computed column that references stored base column
        v1.add_column(int3=v1.int1 + 1)
        # stored computed column that references an unstored and a stored computed view column
        v1.add_column(img1=v1.frame.crop([v1.int3, v1.int3, v1.frame.width, v1.frame.height]), stored=True)
        # computed column that references a stored computed view column
        v1.add_column(int4=v1.frame_idx + 1)
        # unstored computed column that references an unstored and a stored computed view column
        v1.add_column(img2=v1.frame.crop([v1.int4, v1.int4, v1.frame.width, v1.frame.height]), stored=False)

        # create second view
        v2 = cl.create_view('chained_view', v1)
        # computed column that references stored video_t column
        v2.add_column(int5=v2.int1 + 1)
        v2.add_column(int6=v2.int2 + 1)
        # stored computed column that references a stored base column and a stored computed view column;
        # indirectly references int1
        v2.add_column(img3=v2.img1.crop([v2.int5, v2.int5, v2.img1.width, v2.img1.height]), stored=True)
        # stored computed column that references an unstored base column and a manually updated column from video_t;
        # indirectly references int2
        v2.add_column(img4=v2.img2.crop([v2.int6, v2.int6, v2.img2.width, v2.img2.height]), stored=True)
        # comuted column that indirectly references int1 and int2
        v2.add_column(int7=v2.img3.width + v2.img4.width)

        def check_view():
            assert_resultset_eq(
                v1.select(v1.int3).order_by(v1.video, v1.pos).collect(),
                v1.select(v1.int1 + 1).order_by(v1.video, v1.pos).collect())
            assert_resultset_eq(
                v1.select(v1.int4).order_by(v1.video, v1.pos).collect(),
                v1.select(v1.frame_idx + 1).order_by(v1.video, v1.pos).collect())
            assert_resultset_eq(
                v1\
                    .select(v1.video, v1.img1.width, v1.img1.height)\
                    .order_by(v1.video, v1.pos).collect(),
                v1\
                    .select(v1.video, v1.frame.width - v1.int1 - 1, v1.frame.height - v1.int1 - 1)\
                    .order_by(v1.video, v1.pos).collect())
            assert_resultset_eq(
                v2.select(v2.int5).order_by(v2.video, v2.pos).collect(),
                v2.select(v2.int1 + 1).order_by(v2.video, v2.pos).collect())
            assert_resultset_eq(
                v2.select(v2.int6).order_by(v2.video, v2.pos).collect(),
                v2.select(v2.int2 + 1).order_by(v2.video, v2.pos).collect())
            assert_resultset_eq(
                v2 \
                    .select(v2.video, v2.img3.width, v2.img3.height) \
                    .order_by(v2.video, v2.pos).collect(),
                v2 \
                    .select(v2.video, v2.frame.width - v2.int1 * 2 - 2, v2.frame.height - v2.int1 * 2 - 2) \
                    .order_by(v2.video, v2.pos).collect())
            assert_resultset_eq(
                v2 \
                    .select(v2.video, v2.img4.width, v2.img4.height) \
                    .order_by(v2.video, v2.pos).collect(),
                v2 \
                    .select(
                        v2.video, v2.frame.width - v2.frame_idx - v2.int2 - 2,
                        v2.frame.height - v2.frame_idx - v2.int2 - 2) \
                    .order_by(v2.video, v2.pos).collect())
            assert_resultset_eq(
                v2.select(v2.int7).order_by(v2.video, v2.pos).collect(),
                v2.select(v2.img3.width + v2.img4.width).order_by(v2.video, v2.pos).collect())
            assert_resultset_eq(
                v2.select(v2.int7).order_by(v2.video, v2.pos).collect(),
                v2.select(v2.frame.width - v2.int1 * 2 - 2 + v2.frame.width - v2.frame_idx - v2.int2 - 2)\
                    .order_by(v2.video, v2.pos).collect())

        # load data
        rows = [{'video': p, 'int1': i, 'int2': len(video_filepaths) - i} for i, p in enumerate(video_filepaths)]
        status = video_t.insert(rows)
        assert status.num_rows == video_t.count() + v1.count() + v2.count()
        check_view()

        # update int1: propagates to int3, img1, int5, img3, int7
        # TODO: how to test that img4 doesn't get recomputed as part of the computation of int7?
        # need to collect more runtime stats (eg, called functions)
        import urllib
        video_url = urllib.parse.urljoin('file:', urllib.request.pathname2url(video_filepaths[0]))
        status = video_t.update({'int1': video_t.int1 + 1}, where=video_t.video == video_url)
        assert status.num_rows == 1 + v1.where(v1.video == video_url).count() + v2.where(v2.video == video_url).count()
        assert sorted('int1 int3 img1 int5 img3 int7'.split()) == sorted([str.split('.')[1] for str in status.updated_cols])
        check_view()

        # update int2: propagates to img4, int6, int7
        status = video_t.update({'int2': video_t.int2 + 1}, where=video_t.video == video_url)
        assert status.num_rows == 1 + v2.where(v2.video == video_url).count()
        assert sorted('int2 img4 int6 int7'.split()) == sorted([str.split('.')[1] for str in status.updated_cols])
        check_view()