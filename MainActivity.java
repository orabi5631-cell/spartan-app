package com.spartan.cards;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
  @Override
  public void onCreate(Bundle savedInstanceState) {
    registerPlugin(VodafonePurchasePlugin.class);
    super.onCreate(savedInstanceState);
  }
}
