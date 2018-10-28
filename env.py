import numpy as np
from scipy.ndimage.filters import gaussian_filter
from scipy.ndimage.morphology import binary_fill_holes

PEN_DOWN = 0
PEN_UP = 1
FINISH = 2

class Environment():
    # Pulls in new images with generator_fn
    # generator_fn should return a preprocessed image and a segmentation mask
    def __init__(self, generator_fn, gaussian_std=2.0, img_shape=(256,256), alpha=0.05):
        self.generator_fn = generator_fn
        self.gaussian_std = gaussian_std
        self.img_shape = img_shape
        self.alpha = 0.05

        self.curr_image = None
        self.curr_mask = None
        self.curr_blurred_mask = None
        self.state_map = None
        self.last_action = None
        self.first_vertex = None

        self.reset()

    # Returns (new_state, reward, done)
    # Action should be (int, (int, int))
    # First int is 0 = pen down, 1 = pen up, 2 = finish 
    # Int tuple is coordinates for pen down
    # New state is 
    def step(self, action):
        action_class, (coord_x, coord_y) = action
        if self.last_action == PEN_UP:
            if action_class == PEN_UP:
                return self._get_state(), -1.0, False
            elif action_class == PEN_DOWN:
                self.first_vertex = (coord_x, coord_y)
                self.state_map[2,:,:] = 0
                self.state_map[2, coord_x, coord_y] = 1
                self.state_map[1, coord_x, coord_y] = 1
                rew = self.curr_blurred_mask[coord_x, coord_y] / self.alpha
                return self._get_state(), rew, False
            else:
                return self._get_state(), -1.0, True
        elif self.last_action == PEN_DOWN:
            if action_class == PEN_UP:
                rew = self._finish_polygon(coord_x, coord_y)
                self.first_vertex = None
                return self._get_state(), rew, False 
            
            elif action_class == PEN_DOWN:
                prev_vertex_x, prev_vertex_y = np.where(self.state_map[3] == 1)
                prev_vertex_x = prev_vertex_x[0]
                prev_vertex_y = prev_vertex_y[0]

                line_x, line_y = self._get_line_coordinates(prev_vertex_x, prev_vertex_y, coord_x, coord_y)
                rew = self._contour_reward(line_x, line_y)
                for x, y in zip(line_x, line_y):
                    self.state_map[1, x, y] = 1
                
                self.state_map[2, prev_vertex_x, prev_vertex_y] = 0
                self.state_map[2, coord_x, coord_y] = 1

                return self._get_state(), rew, False

            else:
                rew = self._finish_polygon(coord_x, coord_y)
                return self._get_state(), rew, True

        else:
            raise Exception('Environment is done, should have been reset') 
    
    # Returns initial state
    def reset(self):
        self.curr_image, self.curr_mask = self.generator_fn.next()
        assert(self.curr_image.shape == self.img_shape)
        assert(self.curr_mask.shape == self.img_shape)

        self.curr_blurred_mask = gaussian_filter(self.curr_mask.astype(np.float32), self.gaussian_std)
        self.curr_mask = self.curr_mask.astype(np.bool_)
        self.state_map = np.zeros((3, self.img_shape[0], self.img_shape[1]), dtype=np.int16)

        self.last_action = PEN_UP
        self.first_vertex = None

    def _get_state(self):
        return np.concatenate((self.curr_image, self.state_map))
    
    def _contour_reward(self, line_x, line_y):
        rew = 0.0
        for x, y in zip(line_x, line_y):
            rew += self.curr_blurred_mask[x, y]
        return rew / self.alpha
    
    def _region_reward(self):
        assert(self.curr_mask.dtype == np.bool_)
        mask = self.state_map[1].astype(np.bool_)
        intersection = (mask * self.curr_mask).sum()
        union = (mask + self.curr_mask).sum()
        iou = float(intersection) / float(union)
        return iou

    def _get_line_coordinates(self, x0, y0, x1, y1):
        length = int(np.hypot(x1 - x0, y1 - y0))
        x, y = np.linspace(x0, x1, length), np.linspace(y0, y1, length)
        return x.astype(np.int), y.astype(np.int)
    
    # Returns contour reward + region reward for a finished polygon
    def _finish_polygon(self, last_x, last_y):
        last_line_x, last_line_y = self._get_line_coordinates(last_x, last_y, self.first_vertex[0], self.first_vertex[1])
        rew = self._contour_reward(last_line_x, last_line_y)
        for x, y in zip(last_line_x, last_line_y):
            self.state_map[1, x, y] = 1
        # Fill in polygon
        self.state_map[1] = binary_fill_holes(self.state_map[1])
        rew += self._region_reward()

        # Add polygon to overall segmentation mask
        polys = self.state_map[0]
        polys += self.state_map[1]
        polys[polys > 1] = 1

        self.state_map[1,:,:] = 0
        self.state_map[2,:,:] = 0

        return rew