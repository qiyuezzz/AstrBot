import { createVuetify } from 'vuetify';
import '@mdi/font/css/materialdesignicons.css';
import * as components from 'vuetify/components';
import * as directives from 'vuetify/directives';
import { PurpleTheme } from '@/theme/LightTheme';
import { PurpleThemeDark } from "@/theme/DarkTheme";

export default createVuetify({
  components,
  directives,

  theme: {
    defaultTheme: 'PurpleTheme',
    themes: {
      PurpleTheme,
      PurpleThemeDark
    }
  },
  defaults: {
    VBtn: {},
    VCard: {
      rounded: 'lg'
    },
    VTextField: {
      rounded: 'lg'
    },
    VTooltip: {
      // set v-tooltip default location to top
      location: 'top'
    }
  }
});
