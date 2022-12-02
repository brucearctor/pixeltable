import tensorflow as tf
import copy

from pixeltable import catalog
from pixeltable.functions import dict_map
import pixeltable.tf


class TestTf:
    def verify_type(self, df: pixeltable.DataFrame, ds: tf.data.Dataset) -> None:
        """
        Verify that column types of df matches element spec of ds.
        """
        result_set = df.show(1)
        assert isinstance(ds.element_spec, tuple)
        assert len(result_set.col_types) == len(ds.element_spec)
        for i in range(len(result_set.col_types)):
            col_type = result_set.col_types[i]
            if col_type.is_scalar_type():
                assert ds.element_spec[i].shape == ()
            if col_type.is_image_type():
                assert ds.element_spec[i].shape == (col_type.height, col_type.width, col_type.num_channels)

    def test_basic(self, test_img_tbl: catalog.Table) -> None:
        t = test_img_tbl
        m = t[t.category].categorical_map()
        # image types with increasingly specific dimensions
        df = t[t.img, dict_map(t.category, m)]
        ds = pixeltable.tf.to_dataset(df)
        self.verify_type(df, ds)
        for row in ds:
            pass

        df = t[t.img.resize((224, 224))]
        ds = pixeltable.tf.to_dataset(df)
        self.verify_type(df, ds)
        for row in ds:
            pass

        df = t[t.img.convert('RGB').resize((224, 224)), dict_map(t.category, m)]
        ds = pixeltable.tf.to_dataset(df)
        self.verify_type(df, ds)
        for row in ds:
            pass
